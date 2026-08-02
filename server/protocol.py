from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal, Optional

PROTOCOL_ID = "robot-backend/1"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now_ms() -> int:
    return int(time.time() * 1000)


def dumps_message(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False)


def loads_message(text: str) -> dict[str, Any]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("message must be an object")
    return data


def base_envelope(message_type: str, *, msg_id: Optional[str] = None, session_id: Optional[str] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"v": PROTOCOL_ID, "type": message_type, "ts_ms": now_ms()}
    if msg_id is not None:
        out["id"] = msg_id
    if session_id is not None:
        out["session_id"] = session_id
    return out


ActionGroup = Literal["speak", "move", "go_to", "system", "memory"]


def command_message(
    *,
    cmd_id: str,
    name: str,
    group: ActionGroup,
    args: dict[str, Any],
    requires_ack: bool = True,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    out = base_envelope("cmd", msg_id=cmd_id, session_id=session_id)
    out["cmd"] = {"id": cmd_id, "name": name, "group": group, "args": args, "requires_ack": requires_ack}
    return out


def ack_message(*, cmd_id: str, status: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("cmd.ack", session_id=session_id)
    out["ack"] = {"cmd_id": cmd_id, "status": status}
    return out


def status_message(*, state: str, detail: Optional[str] = None, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("status", session_id=session_id)
    out["state"] = state
    if detail is not None:
        out["detail"] = detail
    return out


def asr_final_message(*, utterance_id: str, text: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("asr.final", session_id=session_id)
    out["utterance_id"] = utterance_id
    out["text"] = text
    return out


def llm_requested_message(*, request_id: str, model: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("llm.requested", session_id=session_id)
    out["request_id"] = request_id
    out["model"] = model
    return out


def llm_result_message(*, request_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("llm.result", session_id=session_id)
    out["request_id"] = request_id
    return out


def memory_suggest_message(*, items: list[dict[str, Any]], session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("memory.suggest", session_id=session_id)
    out["items"] = items
    return out


def tts_start_message(*, tts_id: str, text: str, audio_format: str = "wav", session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("tts.start", msg_id=tts_id, session_id=session_id)
    out["tts"] = {"id": tts_id, "text": text, "audio_format": audio_format}
    return out


def tts_end_message(*, tts_id: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("tts.end", msg_id=tts_id, session_id=session_id)
    out["tts"] = {"id": tts_id}
    return out


def error_message(*, code: str, message: str, session_id: Optional[str] = None) -> dict[str, Any]:
    out = base_envelope("error", session_id=session_id)
    out["error"] = {"code": code, "message": message}
    return out
