from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v is not None and v != "" else default


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    audio_idle_seconds: float
    audio_max_bytes: int

    stt_model: str
    stt_stub_text: str

    tts_enabled: bool
    piper_model_path: str
    piper_config_path: str

    llm_enabled: bool
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float

    legacy_text_commands: bool


def load_settings() -> Settings:
    return Settings(
        host=_env_str("ROBOT_BACKEND_HOST", "0.0.0.0"),
        port=_env_int("ROBOT_BACKEND_PORT", 8002),
        audio_idle_seconds=_env_float("ROBOT_BACKEND_AUDIO_IDLE_SECONDS", 0.9),
        audio_max_bytes=_env_int("ROBOT_BACKEND_AUDIO_MAX_BYTES", 2_000_000),
        stt_model=_env_str("ROBOT_BACKEND_STT_MODEL", "small.en"),
        stt_stub_text=_env_str("ROBOT_BACKEND_STT_STUB_TEXT", ""),
        tts_enabled=_env_bool("ROBOT_BACKEND_TTS_ENABLED", True),
        piper_model_path=_env_str("ROBOT_BACKEND_PIPER_MODEL_PATH", "voices/en_GB-alba-medium.onnx"),
        piper_config_path=_env_str("ROBOT_BACKEND_PIPER_CONFIG_PATH", "voices/en_GB-alba-medium.onnx.json"),
        llm_enabled=_env_bool("ROBOT_BACKEND_LLM_ENABLED", False),
        ollama_base_url=_env_str("ROBOT_BACKEND_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=_env_str("ROBOT_BACKEND_OLLAMA_MODEL", "llama3.2:3b"),
        ollama_timeout_seconds=_env_float("ROBOT_BACKEND_OLLAMA_TIMEOUT_SECONDS", 30.0),
        legacy_text_commands=_env_bool("ROBOT_BACKEND_LEGACY_TEXT_COMMANDS", False),
    )
