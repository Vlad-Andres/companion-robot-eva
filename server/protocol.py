from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

PROTOCOL_ID = "eva/1"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now_ms() -> int:
    return int(time.time() * 1000)


def dumps_message(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def base_envelope(message_type: str, *, message_id: Optional[str] = None, session_id: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"v": PROTOCOL_ID, "type": message_type, "ts_ms": now_ms()}
    if message_id is not None:
        out["id"] = message_id
    if session_id is not None:
        out["session_id"] = session_id
    return out


def hello_message(*, supported_protocols: list[str], session_id: Optional[str] = None) -> dict[str, Any]:
    """
    The server's own declaration, sent before the robot says anything.

    It goes out immediately rather than waiting for the robot's manifest:
    firmware older than the handshake never sends one, and it still needs to
    know it is connected.
    """
    out = base_envelope("hello", session_id=session_id)
    out["protocol"] = PROTOCOL_ID
    out["supported_protocols"] = supported_protocols
    return out


def capabilities_ack_message(
    *,
    protocol: str,
    sensors: list[str],
    actuators: list[str],
    actions: list[dict[str, Any]],
    unknown: list[str],
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    What the server took from the robot's manifest.

    `actions` is the half that matters to the robot: the exact set of commands
    this session can send it, so anything else arriving is a bug on the server
    rather than something the robot has to guess about.
    """
    out = base_envelope("capabilities.ack", session_id=session_id)
    out["protocol"] = protocol
    out["accepted"] = {"sensors": sensors, "actuators": actuators}
    out["actions"] = actions
    if unknown:
        out["unknown"] = unknown
    return out


def command_message(
    *,
    command_id: str,
    name: str,
    args: dict[str, Any],
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    out = base_envelope("command", message_id=command_id, session_id=session_id)
    out["command"] = {"id": command_id, "name": name, "args": args}
    return out


def status_message(*, state: str, detail: Optional[str] = None, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("status", session_id=session_id)
    out["state"] = state
    if detail is not None:
        out["detail"] = detail
    return out


def transcript_final_message(*, utterance_id: str, text: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("transcript.final", session_id=session_id)
    out["utterance_id"] = utterance_id
    out["text"] = text
    return out


def language_model_requested_message(*, request_id: str, model: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("language_model.requested", session_id=session_id)
    out["request_id"] = request_id
    out["model"] = model
    return out


def language_model_result_message(*, request_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("language_model.result", session_id=session_id)
    out["request_id"] = request_id
    return out


def memory_suggest_message(*, items: list[dict[str, Any]], session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("memory.suggest", session_id=session_id)
    out["items"] = items
    return out


def speech_start_message(*, speech_id: str, text: str, audio_format: str = "wav", session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("speech.start", message_id=speech_id, session_id=session_id)
    out["speech"] = {"id": speech_id, "text": text, "audio_format": audio_format}
    return out


def speech_end_message(*, speech_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("speech.end", message_id=speech_id, session_id=session_id)
    out["speech"] = {"id": speech_id}
    return out


def error_message(*, code: str, message: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("error", session_id=session_id)
    out["error"] = {"code": code, "message": message}
    return out
