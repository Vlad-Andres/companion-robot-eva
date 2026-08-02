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
from language_model import LanguageModelClient
from log import logger
from planner import plan_from_transcript
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
from text_to_speech import TextToSpeechEngine

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
    audio_buffer: bytearray
    ignore_until: float
    running: bool


async def _send_json(websocket: WebSocket, message: dict[str, Any]) -> None:
    await websocket.send_text(dumps_message(message))


async def _finalize_utterance(session: WebSocketSession, websocket: WebSocket, utterance_id: str, audio: bytes) -> None:
    text = session.speech_to_text.transcribe(audio, session.audio_format).strip()
    if not text:
        return

    await _send_json(websocket, transcript_final_message(utterance_id=utterance_id, text=text, session_id=session.session_id))

    plan = plan_from_transcript(text)

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
    for command in plan.commands:
        await _send_json(websocket, command_message(command_id=new_id("command"), name=command["name"], args=command["args"], session_id=session.session_id))
        session.ignore_until = max(session.ignore_until, time.monotonic() + 1.0)

    if plan.language_model_input_text is not None and session.settings.language_model_enabled:
        request_id = new_id("language_model")
        await _send_json(websocket, status_message(state="thinking", session_id=session.session_id))
        await _send_json(websocket, language_model_requested_message(request_id=request_id, model=session.settings.ollama_model, session_id=session.session_id))
        reply_text = await session.language_model.chat(system_prompt="Reply with plain text only.", user_text=plan.language_model_input_text)
        await _send_json(websocket, language_model_result_message(request_id=request_id, session_id=session.session_id))
        if reply_text and session.settings.text_to_speech_enabled:
            speech_id = new_id("speech")
            await _send_json(websocket, speech_start_message(speech_id=speech_id, text=reply_text, session_id=session.session_id))
            wav = await asyncio.to_thread(session.text_to_speech.synthesize_wav, reply_text)
            if wav:
                await websocket.send_bytes(wav)
            await _send_json(websocket, speech_end_message(speech_id=speech_id, session_id=session.session_id))
            session.ignore_until = max(session.ignore_until, time.monotonic() + 1.5)
        await _send_json(websocket, status_message(state="ready", session_id=session.session_id))


async def _audio_loop(session: WebSocketSession, websocket: WebSocket) -> None:
    while session.running:
        try:
            item = await asyncio.wait_for(session.audio_queue.get(), timeout=session.settings.audio_idle_seconds)
        except asyncio.TimeoutError:
            if session.audio_buffer and time.monotonic() >= session.ignore_until:
                audio = bytes(session.audio_buffer)
                session.audio_buffer.clear()
                await _finalize_utterance(session, websocket, new_id("utterance"), audio)
            continue

        if isinstance(item, _AudioEnd):
            if session.audio_buffer and time.monotonic() >= session.ignore_until:
                audio = bytes(session.audio_buffer)
                session.audio_buffer.clear()
                await _finalize_utterance(session, websocket, item.utterance_id, audio)
            continue

        if time.monotonic() < session.ignore_until:
            session.audio_buffer.clear()
            continue

        if len(session.audio_buffer) + len(item) > session.settings.audio_max_bytes:
            session.audio_buffer.clear()
            await _send_json(websocket, error_message(code="audio_buffer_overflow", message="audio buffer overflow", session_id=session.session_id))
            continue

        session.audio_buffer.extend(item)


async def run_websocket_session(websocket: WebSocket, *, settings: Settings, speech_to_text: SpeechToTextEngine, text_to_speech: TextToSpeechEngine, language_model: LanguageModelClient, dataset_recorder: DatasetRecorder) -> None:
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
        audio_buffer=bytearray(),
        ignore_until=0.0,
        running=True,
    )

    await _send_json(websocket, base_envelope("hello", session_id=session.session_id))
    await _send_json(websocket, status_message(state="ready", session_id=session.session_id))

    audio_task = asyncio.create_task(_audio_loop(session, websocket))
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
