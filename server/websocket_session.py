from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from actions import (
    available_action_names,
    describe_actions,
    describe_actions_for_prompt,
    reply_schema,
    validate_command,
)
from capabilities import (
    ASSUMED_CAPABILITIES,
    SUPPORTED_PROTOCOLS,
    ProtocolMismatch,
    RobotCapabilities,
    negotiate_protocol,
    parse_capabilities,
    unknown_hardware,
)
from config import Settings
from dataset_recorder import DatasetRecorder
import numpy as np

from endpointing import FRAME_SECONDS, SAMPLE_RATE, Endpointer, frames_from_pcm16
from language_model import LanguageModelClient
from log import logger
from planner import plan_from_transcript
from reply_stream import ReplyStream
from sentences import SentenceAccumulator
from protocol import (
    PROTOCOL_ID,
    transcript_final_message,
    base_envelope,
    capabilities_ack_message,
    command_message,
    dumps_message,
    error_message,
    hello_message,
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
    protocol: str
    # What the robot on the other end says it has, and what that leaves it able
    # to be asked for. Both are replaced when its manifest arrives.
    capabilities: RobotCapabilities
    allowed_actions: set[str]


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
        plan = plan_from_transcript(text, allowed=session.allowed_actions)
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
    for command in plan.commands:
        await _dispatch(session, websocket, command)

    if plan.language_model_input_text is not None and session.settings.language_model_enabled:
        await _stream_reply(session, websocket, plan.language_model_input_text)


async def _dispatch(session: WebSocketSession, websocket: WebSocket, command: dict[str, Any]) -> None:
    """
    Perform one validated command.

    "speak" is fulfilled here rather than sent on: the server owns the
    synthesiser, and the robot has no voice of its own — sending it as a
    command is how rule confirmations used to go out silently.
    """
    if command["name"] == "speak":
        await _speak(session, websocket, command["args"]["text"])
        return

    await _send_json(websocket, command_message(command_id=new_id("command"), name=command["name"], args=command["args"], session_id=session.session_id))
    session.telemetry.emit("command", name=command["name"], args=command["args"])
    session.ignore_until = max(session.ignore_until, time.monotonic() + 1.0)


_BASE_PROMPT = (
    "You are Eva, a small companion robot. Reply in one or two short spoken "
    "sentences. Plain text only — no markdown, no lists, no emoji."
)


def _system_prompt(capabilities: RobotCapabilities, *, structured: bool) -> str:
    """
    The prompt for this robot, not for robots in general.

    When the reply is schema-constrained the grammar already makes an
    unavailable action impossible to name; the vocabulary is repeated here
    because a model told what the names mean picks the right one, where a model
    left to discover them by rejection picks the first one that parses.
    """
    if not structured:
        return _BASE_PROMPT

    return (
        f"{_BASE_PROMPT}\n\n"
        "Reply as JSON with two fields. Put what you say out loud in `say`, in "
        "the same one or two short sentences. Put any actions in `commands`, "
        "and leave it empty when the reply is only conversation — most replies "
        "are. Never describe an action in `say` that is not also in `commands`.\n\n"
        f"Actions you can perform:\n{describe_actions_for_prompt(capabilities)}"
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
    Speak the reply sentence by sentence as the model writes it, then act on it.

    Waiting for the full reply and then synthesising all of it means the robot
    is silent for the sum of both. Sending each sentence as it completes gets
    Eva talking while the rest is still being generated — and that stays true
    when the reply is a JSON object, because ReplyStream reads the spoken field
    out of it as the characters arrive.

    Commands land after the speech, since they come after `say` in the object.
    On a two-sentence reply that is a couple of hundred milliseconds, and it
    reads the right way round anyway: Eva says she is moving, then moves.
    """
    request_id = new_id("language_model")
    schema = reply_schema(session.capabilities) if session.settings.model_actions_enabled else None
    await _send_json(websocket, status_message(state="thinking", session_id=session.session_id))
    await _send_json(
        websocket,
        language_model_requested_message(request_id=request_id, model=session.settings.ollama_model, session_id=session.session_id),
    )

    session.telemetry.emit("state", state="thinking")

    reply = ReplyStream()
    accumulator = SentenceAccumulator()
    spoke = False
    started = time.perf_counter()

    async def speak_from(text: str) -> None:
        nonlocal spoke
        for sentence in accumulator.add(text):
            if not spoke:
                # The number that decides whether Eva feels responsive: how
                # long until she can start saying anything at all.
                session.telemetry.emit(
                    "stage", stage="llm_first_sentence",
                    ms=round((time.perf_counter() - started) * 1000, 1),
                )
            await _speak(session, websocket, sentence)
            spoke = True

    outcome = None
    try:
        async for piece in session.language_model.stream(
            system_prompt=_system_prompt(session.capabilities, structured=schema is not None),
            user_text=prompt,
            response_format=schema,
        ):
            for text in reply.add(piece):
                await speak_from(text)
        outcome = reply.finish()
        if outcome.text:
            await speak_from(outcome.text)
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

    if outcome is not None:
        if outcome.truncated:
            # The words survived; the actions did not. Worth a line in the log,
            # because the fix is a bigger EVA_OLLAMA_MAX_REPLY_TOKENS and there
            # is nothing else to see from the outside.
            _log.warning("Model reply was cut off before its commands; raise the reply token budget.")
        await _perform_model_commands(session, websocket, outcome.commands)

    await _send_json(websocket, language_model_result_message(request_id=request_id, session_id=session.session_id))
    await _send_json(websocket, status_message(state="ready", session_id=session.session_id))


async def _perform_model_commands(session: WebSocketSession, websocket: WebSocket, commands: list[dict[str, Any]]) -> None:
    """
    Validate what the model asked for, then do it.

    The grammar constrains the shape of the reply, not its sense: it guarantees
    a well-formed command object, not that the object means anything. This is
    the gate that decides, and it is the same one the rule path goes through.
    """
    for raw in commands:
        command = validate_command(raw, session.allowed_actions)
        if command is None:
            _log.warning("Rejected command from the model: %r", raw)
            continue
        await _dispatch(session, websocket, command)


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


def _apply_audio_format(session: WebSocketSession, fmt: Any) -> None:
    """Override the assumed PCM format, from `audio.format` or the manifest."""
    if not isinstance(fmt, dict):
        return
    encoding = fmt.get("encoding")
    sample_rate = fmt.get("sample_rate_hz")
    channels = fmt.get("channels")
    if isinstance(encoding, str) and isinstance(sample_rate, int) and isinstance(channels, int):
        session.audio_format = AudioFormat(encoding=encoding, sample_rate_hz=sample_rate, channels=channels)


async def _accept_capabilities(session: WebSocketSession, websocket: WebSocket, data: dict[str, Any]) -> bool:
    """
    Take the robot's manifest and answer with what it bought.

    Returns False when the session cannot continue. A robot that speaks no
    version this server knows is told so and disconnected rather than left to
    stream audio nobody will answer — a protocol mismatch that limps is much
    harder to diagnose than one that stops.
    """
    try:
        session.protocol = negotiate_protocol(data, default=session.protocol)
    except ProtocolMismatch as mismatch:
        _log.warning("Rejecting robot: %s", mismatch)
        await _send_json(
            websocket,
            error_message(code="protocol_unsupported", message=str(mismatch), session_id=session.session_id),
        )
        await websocket.close(code=1002)
        return False

    capabilities = parse_capabilities(data)
    if capabilities is None:
        _log.warning("Ignoring a capabilities message that declared no hardware.")
        await _send_json(
            websocket,
            error_message(code="empty_capabilities", message="declare at least one sensor or actuator", session_id=session.session_id),
        )
        return True

    session.capabilities = capabilities
    session.allowed_actions = available_action_names(capabilities)
    _apply_audio_format(session, capabilities.extra.get("audio"))

    unknown = unknown_hardware(capabilities)
    _log.info("Robot declared %s", capabilities.describe())
    if unknown:
        _log.info("Ignoring hardware this server has no actions for: %s", ", ".join(unknown))

    await _send_json(
        websocket,
        capabilities_ack_message(
            protocol=session.protocol,
            sensors=sorted(capabilities.sensors),
            actuators=sorted(capabilities.actuators),
            actions=describe_actions(capabilities),
            unknown=unknown,
            session_id=session.session_id,
        ),
    )
    session.telemetry.emit("capabilities", robot=capabilities.describe(), actions=sorted(session.allowed_actions))
    return True


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
        protocol=PROTOCOL_ID,
        # Until the robot says otherwise it is assumed to have everything —
        # see capabilities.py for why that is the safer default.
        capabilities=ASSUMED_CAPABILITIES,
        allowed_actions=available_action_names(ASSUMED_CAPABILITIES),
    )

    await _send_json(websocket, hello_message(supported_protocols=list(SUPPORTED_PROTOCOLS), session_id=session.session_id))
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
            if message_type == "capabilities":
                if not await _accept_capabilities(session, websocket, data):
                    break
                continue
            if message_type == "audio.format":
                _apply_audio_format(session, data.get("format"))
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
