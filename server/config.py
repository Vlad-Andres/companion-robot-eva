from __future__ import annotations

import os
from dataclasses import dataclass


def load_dotenv(path: str = ".env") -> None:
    """
    Load KEY=VALUE lines from a .env file into the environment.

    Existing environment variables win, so an inline override such as
    `EVA_PORT=9000 make server` still takes effect. Blank lines and lines
    starting with # are ignored, and surrounding quotes are stripped.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


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

    speech_to_text_model: str
    speech_to_text_stub_text: str

    text_to_speech_enabled: bool
    text_to_speech_engine: str
    piper_model_path: str
    piper_config_path: str

    language_model_enabled: bool
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float

    legacy_text_commands: bool

    dataset_capture_enabled: bool
    dataset_directory: str
    dataset_max_bytes: int


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        host=_env_str("EVA_HOST", "0.0.0.0"),
        port=_env_int("EVA_PORT", 8002),
        audio_idle_seconds=_env_float("EVA_AUDIO_IDLE_SECONDS", 0.9),
        audio_max_bytes=_env_int("EVA_AUDIO_MAX_BYTES", 2_000_000),
        speech_to_text_model=_env_str("EVA_SPEECH_TO_TEXT_MODEL", "small.en"),
        speech_to_text_stub_text=_env_str("EVA_SPEECH_TO_TEXT_STUB_TEXT", ""),
        text_to_speech_enabled=_env_bool("EVA_TEXT_TO_SPEECH_ENABLED", True),
        text_to_speech_engine=_env_str("EVA_TEXT_TO_SPEECH_ENGINE", "auto"),
        piper_model_path=_env_str("EVA_PIPER_MODEL_PATH", "voices/en_GB-alba-medium.onnx"),
        piper_config_path=_env_str("EVA_PIPER_CONFIG_PATH", "voices/en_GB-alba-medium.onnx.json"),
        language_model_enabled=_env_bool("EVA_LANGUAGE_MODEL_ENABLED", False),
        ollama_base_url=_env_str("EVA_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=_env_str("EVA_OLLAMA_MODEL", "llama3.2:3b"),
        ollama_timeout_seconds=_env_float("EVA_OLLAMA_TIMEOUT_SECONDS", 30.0),
        legacy_text_commands=_env_bool("EVA_LEGACY_TEXT_COMMANDS", False),
        dataset_capture_enabled=_env_bool("EVA_DATASET_CAPTURE_ENABLED", False),
        dataset_directory=_env_str("EVA_DATASET_DIR", "dataset"),
        dataset_max_bytes=_env_int("EVA_DATASET_MAX_BYTES", 2_000_000_000),
    )
