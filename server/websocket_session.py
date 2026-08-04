from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from config import Settings
from dataset_recorder import DatasetRecorder
import numpy as np

from endpointing import FRAME_SECONDS, SAMPLE_RATE, Endpointer, frames_from_pcm16
from language_model import LanguageModelClient
from log import logger
from planner import plan_from_transcript
from sentences import SentenceAccumulator
from protocol import (
    transcript_final_message,
    base_envelope,
    command_message,
    dumps_message,
    error_message,
    language_model_requested_message,
    language_model_result_message,
    memory_suggest_message,
    new_id,
    status_message,
    speech_end_message,
    speech_start_message,
)
from speech_to_text import AudioFormat, SpeechToTextEngine
from telemetry import Telemetry
from text_to_speech import TextToSpeechEngine
from turn_detection import TurnDetector
from voice_activity import FRAME_SAMPLES, VoiceActivityDetector

_log = logger("eva.websocket_session")


def _new_session_id() -> str:
    return f"s_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class _AudioEnd:
    utterance_id: str


@dataclass
class WebSocketSession:
    session_id: str
    settings: Settings
    speech_to_text: SpeechToTextEngine
    text_to_speech: TextToSpeechEngine
    language_model: LanguageModelClient
    dataset_recorder: DatasetRecorder
    audio_format: AudioFormat
    audio_queue: asyncio.Queue[bytes | _AudioEnd]
    endpointer: Endpointer
    telemetry: Telemetry
    frame_carry: bytes       # partial frame left over from the last read
    ignore_until: float
    running: bool


async def _send_json(websocket: WebSocket, message: dict[str, Any]) -> None:
    await websocket.send_text(dumps_message(message))


async def _finalize_utterance(session: WebSocketSession, websocket: WebSocket, utterance_id: str, audio: bytes) -> None:
    # Offloaded: transcribe() is CPU-bound and takes ~1s on a small model, which
    # would otherwise stall the receive loop and back audio up in the socket.
    with session.telemetry.timed("stt"):
        text = (await asyncio.to_thread(session.speech_to_text.transcribe, audio, session.audio_format)).strip()
    if not text:
        return

    await _send_json(websocket, transcript_final_message(utterance_id=utterance_id, text=text, session_id=session.session_id))

    with session.telemetry.timed("plan"):
        plan = plan_from_transcript(text)
    session.telemetry.emit("transcript", text=text, rule=plan.rule_key)

    session.dataset_recorder.record(
        audio=audio,
        transcript=text,
        label=plan.rule_key or "none",
        label_source="rule" if plan.rule_key else "dialogue",
        sample_rate_hz=session.audio_format.sample_rate_hz,
        channels=session.audio_format.channels,
        session_id=session.session_id,
        utterance_id=utterance_id,
    )

    if plan.memory_items:
        await _send_json(websocket, memory_suggest_message(items=plan.memory_items, session_id=session.session_id))

    # Commands arrive validated by the planner against the action registry.
    # "speak" is fulfilled here rather than sent on: the server owns the
    # synthesiser, and the robot has no voice of its own — sending it as a
    # command is how rule confirmations used to go out silently.
    for command in plan.commands:
        if command["name"] == "speak":
            await _speak(session, websocket, command["args"]["text"])
            continue

        await _send_json(websocket, command_message(command_id=new_id("command"), name=command["name"], args=command["args"], session_id=session.session_id))
        session.ignore_until = max(session.ignore_until, time.monotonic() + 1.0)

    if plan.language_model_input_text is not None and session.settings.language_model_enabled:
        await _stream_reply(session, websocket, plan.language_model_input_text)


SYSTEM_PROMPT = (
    "You are Eva, a small companion robot. Reply in one or two short spoken "
    "sentences. Plain text only — no markdown, no lists, no emoji."
)


async def _speak(session: WebSocketSession, websocket: WebSocket, text: str) -> None:
    """Synthesize one piece of speech and send it, text first then audio."""
    if not text or not session.settings.text_to_speech_enabled:
        return

    speech_id = new_id("speech")
    await _send_json(websocket, speech_start_message(speech_id=speech_id, text=text, session_id=session.session_id))
    session.telemetry.emit("reply", text=text)
    with session.telemetry.timed("tts"):
        wav = await asyncio.to_thread(session.text_to_speech.synthesize_wav, text)
    if wav:
        await websocket.send_bytes(wav)
    await _send_json(websocket, speech_end_message(speech_id=speech_id, session_id=session.session_id))
    # Stay deaf a little past the audio so Eva does not transcribe herself.
    session.ignore_until = max(session.ignore_until, time.monotonic() + 1.5)


async def _stream_reply(session: WebSocketSession, websocket: WebSocket, prompt: str) -> None:
    """
    Speak the reply sentence by sentence as the model writes it.

    Waiting for the full reply and then synthesising all of it means the robot
    is silent for the sum of both. Sending each sentence as it completes gets
    Eva talking while the rest is still being generated.
    """
    request_id = new_id("language_model")
    await _send_json(websocket, status_message(state="thinking", session_id=session.session_id))
    await _send_json(
        websocket,
        language_model_requested_message(request_id=request_id, model=session.settings.ollama_model, session_id=session.session_id),
    )

    session.telemetry.emit("state", state="thinking")

    accumulator = SentenceAccumulator()
    spoke = False
    started = time.perf_counter()
    try:
        async for piece in session.language_model.stream(system_prompt=SYSTEM_PROMPT, user_text=prompt):
            for sentence in accumulator.add(piece):
                if not spoke:
                    # The number that decides whether Eva feels responsive:
                    # how long until she can start saying anything at all.
                    session.telemetry.emit(
                        "stage", stage="llm_first_sentence",
                        ms=round((time.perf_counter() - started) * 1000, 1),
                    )
                await _speak(session, websocket, sentence)
                spoke = True
    except Exception as exc:
        _log.warning("Language model stream failed: %s", exc)

    remainder = accumulator.finish()
    if remainder:
        await _speak(session, websocket, remainder)
        spoke = True

    session.telemetry.emit(
        "stage", stage="llm_total", ms=round((time.perf_counter() - started) * 1000, 1)
    )

    if not spoke:
        _log.info("Language model produced no reply.")

    await _send_json(websocket, language_model_result_message(request_id=request_id, session_id=session.session_id))
    await _send_json(websocket, status_message(state="ready", session_id=session.session_id))


def report_audio_task_failure(task: asyncio.Task) -> None:
    """
    Say so when the audio loop dies.

    Without this an unhandled exception in the task leaves the session simply
    deaf: audio keeps arriving, nothing processes it, and nothing is logged.
    That is indistinguishable from "the robot stopped hearing me".
    """
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _log.error("Audio loop stopped: %r", error)


async def _audio_loop(session: WebSocketSession, websocket: WebSocket) -> None:
    """
    Feed every arriving frame to the endpointer and act on completed turns.

    There is no idle timer here any more. The endpointer decides where an
    utterance ends from the audio itself, so nothing depends on frames
    arriving faster than some timeout — which is what used to cut sentences
    in half whenever the chunk period outran it.
    """
    while session.running:
        item = await session.audio_queue.get()

        if isinstance(item, _AudioEnd):
            # The robot can still force an endpoint, but nothing requires it to.
            utterance = session.endpointer.flush()
            if utterance and time.monotonic() >= session.ignore_until:
                await _finalize_utterance(session, websocket, item.utterance_id, utterance)
            continue

        if time.monotonic() < session.ignore_until:
            # Eva is talking. Drop her own voice and forget the partial turn.
            session.frame_carry = b""
            session.endpointer.reset()
            continue

        frames, session.frame_carry = frames_from_pcm16(item, session.frame_carry)

        for frame in frames:
            was_speaking = session.endpointer.in_speech
            utterance = session.endpointer.push(frame)

            if session.telemetry.enabled:
                session.telemetry.frame(
                    rms=float(np.sqrt(np.mean(np.square(frame)))),
                    speech_probability=session.endpointer.last_speech_probability,
                    in_speech=session.endpointer.in_speech,
                )

            if session.endpointer.in_speech and not was_speaking:
                await _send_json(websocket, status_message(state="listening", session_id=session.session_id))
                session.telemetry.emit("state", state="listening")

            if utterance is not None:
                frame_count = len(utterance) // 2 // FRAME_SAMPLES
                session.telemetry.emit(
                    "utterance",
                    seconds=round(len(utterance) / 2 / SAMPLE_RATE, 3),
                    frames=frame_count,
                    preroll=round(session.endpointer.preroll_frames_used * FRAME_SECONDS, 3),
                )
                await _finalize_utterance(session, websocket, new_id("utterance"), utterance)
                session.telemetry.emit("turn_end")
                session.telemetry.emit("state", state="idle")
                if time.monotonic() < session.ignore_until:
                    # Replying invalidates anything captured while we spoke.
                    session.frame_carry = b""
                    session.endpointer.reset()
                    break


async def run_websocket_session(websocket: WebSocket, *, settings: Settings, speech_to_text: SpeechToTextEngine, text_to_speech: TextToSpeechEngine, language_model: LanguageModelClient, dataset_recorder: DatasetRecorder, voice_activity: VoiceActivityDetector, turn_detector: TurnDetector, telemetry: Telemetry) -> None:
    await websocket.accept()
    session = WebSocketSession(
        session_id=_new_session_id(),
        settings=settings,
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
        language_model=language_model,
        dataset_recorder=dataset_recorder,
        audio_format=AudioFormat(),
        audio_queue=asyncio.Queue(maxsize=256),
        # Each connection gets its own endpointer: the detectors carry state
        # between frames and must not be shared across sessions.
        endpointer=Endpointer(voice_activity, turn_detector, settings.endpointer),
        telemetry=telemetry,
        frame_carry=b"",
        ignore_until=0.0,
        running=True,
    )

    await _send_json(websocket, base_envelope("hello", session_id=session.session_id))
    await _send_json(websocket, status_message(state="ready", session_id=session.session_id))

    audio_task = asyncio.create_task(_audio_loop(session, websocket))
    audio_task.add_done_callback(report_audio_task_failure)
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            if message.get("bytes") is not None:
                data = message["bytes"]
                if isinstance(data, (bytes, bytearray, memoryview)):
                    try:
                        session.audio_queue.put_nowait(bytes(data))
                    except asyncio.QueueFull:
                        await _send_json(websocket, error_message(code="audio_backpressure", message="audio queue full", session_id=session.session_id))
                continue

            text = message.get("text")
            if not isinstance(text, str):
                continue

            try:
                data = json.loads(text)
            except Exception:
                await _send_json(websocket, error_message(code="bad_json", message="invalid json", session_id=session.session_id))
                continue

            message_type = data.get("type")
            if message_type == "ping":
                await _send_json(websocket, base_envelope("pong", session_id=session.session_id))
                continue
            if message_type == "audio.end":
                utterance_id = data.get("utterance_id")
                if not isinstance(utterance_id, str) or not utterance_id:
                    utterance_id = new_id("utterance")
                try:
                    session.audio_queue.put_nowait(_AudioEnd(utterance_id=utterance_id))
                except asyncio.QueueFull:
                    await _send_json(websocket, error_message(code="audio_backpressure", message="audio queue full", session_id=session.session_id))
                continue
            if message_type == "audio.format":
                fmt = data.get("format")
                if isinstance(fmt, dict):
                    enc = fmt.get("encoding")
                    sr = fmt.get("sample_rate_hz")
                    ch = fmt.get("channels")
                    if isinstance(enc, str) and isinstance(sr, int) and isinstance(ch, int):
                        session.audio_format = AudioFormat(encoding=enc, sample_rate_hz=sr, channels=ch)
                continue
            await _send_json(websocket, error_message(code="unknown_message", message="unknown message type", session_id=session.session_id))
    except WebSocketDisconnect:
        pass
    finally:
        session.running = False
        audio_task.cancel()
        try:
            await audio_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
