from __future__ import annotations

import os
from dataclasses import dataclass

from endpointing import EndpointerSettings

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path: str | None = None) -> None:
    """
    Load KEY=VALUE lines from server/.env into the environment.

    Existing environment variables win, so an inline override such as
    `EVA_PORT=9000 make server` still takes effect. Blank lines and lines
    starting with # are ignored, and surrounding quotes are stripped.

    The file is found relative to this package, not the working directory,
    so the server behaves the same however it was launched.
    """
    path = path or os.path.join(_SERVER_DIR, ".env")
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


def _env_path(key: str, default: str) -> str:
    """
    A filesystem path from the environment, resolved against server/.

    Relative paths are anchored to this package rather than the working
    directory: `make server` runs from server/ but a test runner may not, and
    a model silently "missing" because of cwd degrades to the fallback
    detector instead of failing loudly.
    """
    value = _env_str(key, default)
    return value if os.path.isabs(value) else os.path.join(_SERVER_DIR, value)


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
    audio_max_bytes: int

    # Where an utterance starts and stops — see endpointing.py.
    endpointer: EndpointerSettings
    voice_activity_model_path: str
    turn_detection_enabled: bool
    turn_detection_model_path: str
    turn_detection_threshold: float

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
    ollama_max_reply_tokens: int
    ollama_keep_alive: str

    debug_enabled: bool

    dataset_capture_enabled: bool
    dataset_directory: str
    dataset_max_bytes: int


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        host=_env_str("EVA_HOST", "0.0.0.0"),
        port=_env_int("EVA_PORT", 8002),
        audio_max_bytes=_env_int("EVA_AUDIO_MAX_BYTES", 2_000_000),
        endpointer=EndpointerSettings(
            speech_threshold=_env_float("EVA_VAD_THRESHOLD", 0.5),
            preroll_seconds=_env_float("EVA_PREROLL_SECONDS", 0.3),
            hangover_seconds=_env_float("EVA_HANGOVER_SECONDS", 0.6),
            max_extension_seconds=_env_float("EVA_MAX_EXTENSION_SECONDS", 4.0),
            max_utterance_seconds=_env_float("EVA_MAX_UTTERANCE_SECONDS", 30.0),
        ),
        voice_activity_model_path=_env_path("EVA_VAD_MODEL_PATH", "models/silero_vad.onnx"),
        turn_detection_enabled=_env_bool("EVA_TURN_DETECTION_ENABLED", True),
        turn_detection_model_path=_env_path("EVA_TURN_MODEL_PATH", "models/smart_turn.onnx"),
        turn_detection_threshold=_env_float("EVA_TURN_THRESHOLD", 0.5),
        speech_to_text_model=_env_str("EVA_SPEECH_TO_TEXT_MODEL", "small.en"),
        speech_to_text_stub_text=_env_str("EVA_SPEECH_TO_TEXT_STUB_TEXT", ""),
        text_to_speech_enabled=_env_bool("EVA_TEXT_TO_SPEECH_ENABLED", True),
        text_to_speech_engine=_env_str("EVA_TEXT_TO_SPEECH_ENGINE", "auto"),
        piper_model_path=_env_path("EVA_PIPER_MODEL_PATH", "voices/en_GB-alba-medium.onnx"),
        piper_config_path=_env_path("EVA_PIPER_CONFIG_PATH", "voices/en_GB-alba-medium.onnx.json"),
        language_model_enabled=_env_bool("EVA_LANGUAGE_MODEL_ENABLED", False),
        ollama_base_url=_env_str("EVA_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=_env_str("EVA_OLLAMA_MODEL", "llama3.2:3b"),
        ollama_timeout_seconds=_env_float("EVA_OLLAMA_TIMEOUT_SECONDS", 30.0),
        ollama_max_reply_tokens=_env_int("EVA_OLLAMA_MAX_REPLY_TOKENS", 80),
        ollama_keep_alive=_env_str("EVA_OLLAMA_KEEP_ALIVE", "30m"),
        debug_enabled=_env_bool("EVA_DEBUG_ENABLED", False),
        dataset_capture_enabled=_env_bool("EVA_DATASET_CAPTURE_ENABLED", False),
        dataset_directory=_env_str("EVA_DATASET_DIR", "dataset"),
        dataset_max_bytes=_env_int("EVA_DATASET_MAX_BYTES", 2_000_000_000),
    )
