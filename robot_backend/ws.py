from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .config import Settings
from .llm import LlmClient
from .log import logger
from .planner import plan_from_transcript
from .protocol import (
    asr_final_message,
    base_envelope,
    command_message,
    dumps_message,
    error_message,
    llm_requested_message,
    llm_result_message,
    memory_suggest_message,
    new_id,
    status_message,
    tts_end_message,
    tts_start_message,
)
from .stt import AudioFormat, SttEngine
from .tts import TtsEngine

_log = logger("robot_backend.ws")


def _new_session_id() -> str:
    return f"s_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class _AudioEnd:
    utterance_id: str


@dataclass
class WsSession:
    session_id: str
    settings: Settings
    stt: SttEngine
    tts: TtsEngine
    llm: LlmClient
    audio_format: AudioFormat
    audio_queue: asyncio.Queue[bytes | _AudioEnd]
    audio_buf: bytearray
    last_rx: float
    ignore_until: float
    running: bool


async def _send_json(ws: WebSocket, msg: dict[str, Any]) -> None:
    await ws.send_text(dumps_message(msg))


async def _finalize_utterance(session: WsSession, ws: WebSocket, utterance_id: str, audio: bytes) -> None:
    text = session.stt.transcribe(audio, session.audio_format).strip()
    if not text:
        return

    await _send_json(ws, asr_final_message(utterance_id=utterance_id, text=text, session_id=session.session_id))

    plan = plan_from_transcript(text)
    if plan.memory_items:
        await _send_json(ws, memory_suggest_message(items=plan.memory_items, session_id=session.session_id))

    for cmd in plan.commands:
        name = cmd.get("name")
        group = cmd.get("group")
        args = cmd.get("args")
        if not isinstance(name, str) or not isinstance(group, str) or not isinstance(args, dict):
            continue
        cmd_id = new_id("cmd")
        await _send_json(ws, command_message(cmd_id=cmd_id, name=name, group=group, args=args, requires_ack=True, session_id=session.session_id))

    if plan.llm_user_text is not None and session.settings.llm_enabled:
        req_id = new_id("llm")
        await _send_json(ws, status_message(state="thinking", session_id=session.session_id))
        await _send_json(ws, llm_requested_message(request_id=req_id, model=session.settings.ollama_model, session_id=session.session_id))
        out = await session.llm.chat(system_prompt="Reply with plain text only.", user_text=plan.llm_user_text)
        await _send_json(ws, llm_result_message(request_id=req_id, session_id=session.session_id))
        if out and session.settings.tts_enabled:
            tts_id = new_id("tts")
            await _send_json(ws, tts_start_message(tts_id=tts_id, text=out, session_id=session.session_id))
            wav = await asyncio.to_thread(session.tts.synthesize_wav, out)
            if wav:
                await ws.send_bytes(wav)
            await _send_json(ws, tts_end_message(tts_id=tts_id, session_id=session.session_id))
        await _send_json(ws, status_message(state="ready", session_id=session.session_id))


async def _audio_loop(session: WsSession, ws: WebSocket) -> None:
    while session.running:
        try:
            item = await asyncio.wait_for(session.audio_queue.get(), timeout=session.settings.audio_idle_seconds)
        except asyncio.TimeoutError:
            if session.audio_buf and time.monotonic() >= session.ignore_until:
                audio = bytes(session.audio_buf)
                session.audio_buf.clear()
                await _finalize_utterance(session, ws, new_id("utt"), audio)
            continue

        if isinstance(item, _AudioEnd):
            if session.audio_buf and time.monotonic() >= session.ignore_until:
                audio = bytes(session.audio_buf)
                session.audio_buf.clear()
                await _finalize_utterance(session, ws, item.utterance_id, audio)
            continue

        if time.monotonic() < session.ignore_until:
            session.audio_buf.clear()
            continue

        if len(session.audio_buf) + len(item) > session.settings.audio_max_bytes:
            session.audio_buf.clear()
            await _send_json(ws, error_message(code="audio_buffer_overflow", message="audio buffer overflow", session_id=session.session_id))
            continue

        session.audio_buf.extend(item)
        session.last_rx = time.monotonic()


async def run_ws_session(ws: WebSocket, *, settings: Settings, stt: SttEngine, tts: TtsEngine, llm: LlmClient) -> None:
    await ws.accept()
    session = WsSession(
        session_id=_new_session_id(),
        settings=settings,
        stt=stt,
        tts=tts,
        llm=llm,
        audio_format=AudioFormat(),
        audio_queue=asyncio.Queue(maxsize=256),
        audio_buf=bytearray(),
        last_rx=time.monotonic(),
        ignore_until=0.0,
        running=True,
    )

    await _send_json(ws, base_envelope("hello", session_id=session.session_id))
    await _send_json(ws, status_message(state="ready", session_id=session.session_id))

    audio_task = asyncio.create_task(_audio_loop(session, ws))
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if isinstance(data, (bytes, bytearray, memoryview)):
                    try:
                        session.audio_queue.put_nowait(bytes(data))
                    except asyncio.QueueFull:
                        await _send_json(ws, error_message(code="audio_backpressure", message="audio queue full", session_id=session.session_id))
                continue

            text = msg.get("text")
            if not isinstance(text, str):
                continue

            try:
                data = json.loads(text)
            except Exception:
                if settings.legacy_text_commands:
                    continue
                await _send_json(ws, error_message(code="bad_json", message="invalid json", session_id=session.session_id))
                continue

            mtype = data.get("type")
            if mtype == "ping":
                await _send_json(ws, base_envelope("pong", session_id=session.session_id))
                continue
            if mtype == "audio.end":
                utt = data.get("utterance_id")
                if not isinstance(utt, str) or not utt:
                    utt = new_id("utt")
                try:
                    session.audio_queue.put_nowait(_AudioEnd(utterance_id=utt))
                except asyncio.QueueFull:
                    await _send_json(ws, error_message(code="audio_backpressure", message="audio queue full", session_id=session.session_id))
                continue
            if mtype == "audio.format":
                fmt = data.get("format")
                if isinstance(fmt, dict):
                    enc = fmt.get("encoding")
                    sr = fmt.get("sample_rate_hz")
                    ch = fmt.get("channels")
                    if isinstance(enc, str) and isinstance(sr, int) and isinstance(ch, int):
                        session.audio_format = AudioFormat(encoding=enc, sample_rate_hz=sr, channels=ch)
                continue
            if mtype == "cmd.ack":
                continue
            if settings.legacy_text_commands:
                continue
            await _send_json(ws, error_message(code="unknown_message", message="unknown message type", session_id=session.session_id))
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
