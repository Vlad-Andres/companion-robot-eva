from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .log import logger

_log = logger("robot_backend.stt")

try:
    import numpy as _np
    from faster_whisper import WhisperModel as _WhisperModel
except Exception:
    _np = None
    _WhisperModel = None


@dataclass(frozen=True)
class AudioFormat:
    encoding: str = "pcm_s16le"
    sample_rate_hz: int = 16000
    channels: int = 1


class SttEngine:
    def transcribe(self, audio: bytes, audio_format: AudioFormat) -> str:
        raise NotImplementedError()


class StubSttEngine(SttEngine):
    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, audio: bytes, audio_format: AudioFormat) -> str:
        return self._text


class FasterWhisperSttEngine(SttEngine):
    def __init__(self, model_name: str) -> None:
        if _WhisperModel is None or _np is None:
            raise RuntimeError("faster-whisper is not available")
        self._model = _WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio: bytes, audio_format: AudioFormat) -> str:
        if audio_format.encoding != "pcm_s16le" or audio_format.sample_rate_hz != 16000 or audio_format.channels != 1:
            raise ValueError("unsupported audio format")
        audio_np = _np.frombuffer(audio, dtype=_np.int16).astype(_np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio_np, beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments if s.text).strip()


def build_default_stt_engine(*, model_name: str, stub_text: str) -> SttEngine:
    if stub_text.strip():
        _log.info("STT stub enabled")
        return StubSttEngine(stub_text.strip())

    if _WhisperModel is not None and _np is not None:
        _log.info("Using faster-whisper STT")
        return FasterWhisperSttEngine(model_name)

    _log.warning("No STT engine available; falling back to empty transcript")
    return StubSttEngine("")
