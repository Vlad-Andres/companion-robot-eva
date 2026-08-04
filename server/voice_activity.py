"""
voice_activity.py — Is this frame speech?

Wraps Silero VAD, which answers that far better than an energy threshold: it
scores loud non-speech noise near zero, where an RMS gate opens wide.

The ONNX graph declares its audio input as [None, None] and so accepts a
wrongly sized frame without complaining, returning plausible-looking low
probabilities forever. It actually wants the 64 samples preceding the frame
prepended to it, which this class carries between calls.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

import numpy as np

from log import logger

_log = logger("eva.voice_activity")

# Silero's fixed geometry at 16 kHz. Both are baked into the graph.
FRAME_SAMPLES = 512      # 32 ms — the only frame size the model accepts
CONTEXT_SAMPLES = 64     # carried from the previous frame


class VoiceActivityDetector(Protocol):
    """Scores one frame of audio as speech or not."""

    def speech_probability(self, frame: np.ndarray) -> float:
        """Return P(speech) for one FRAME_SAMPLES frame of float32 in [-1, 1]."""
        ...

    def reset(self) -> None:
        """Forget everything carried between frames. Call between utterances."""
        ...


class SileroVoiceActivityDetector:
    """Silero VAD over onnxruntime — no torch required."""

    def __init__(self, model_path: str) -> None:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        # One frame at a time on one thread: extra threads only add scheduling.
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1

        self._session = onnxruntime.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._sample_rate = np.array(16000, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)

    def speech_probability(self, frame: np.ndarray) -> float:
        if len(frame) != FRAME_SAMPLES:
            raise ValueError(f"expected {FRAME_SAMPLES} samples, got {len(frame)}")

        window = np.concatenate([self._context, frame]).astype(np.float32)[None]
        probability, self._state = self._session.run(
            None, {"input": window, "state": self._state, "sr": self._sample_rate}
        )
        self._context = frame[-CONTEXT_SAMPLES:].astype(np.float32)
        return float(probability[0][0])


class AlwaysSpeechDetector:
    """Fallback when the model is missing: treat everything as speech.

    Degrades to "the server hears one long utterance" rather than to silence,
    which is obvious in the logs instead of mysteriously quiet.
    """

    def speech_probability(self, frame: np.ndarray) -> float:
        return 1.0

    def reset(self) -> None:
        return


def build_voice_activity_detector(model_path: str) -> VoiceActivityDetector:
    if not os.path.exists(model_path):
        _log.warning(
            "Silero VAD model not found at %s — every frame will count as speech. "
            "Fetch it with: make models",
            model_path,
        )
        return AlwaysSpeechDetector()

    try:
        detector = SileroVoiceActivityDetector(model_path)
        _log.info("Voice activity detection: silero (%s)", os.path.basename(model_path))
        return detector
    except Exception as exc:
        _log.warning("Could not load Silero VAD (%s) — every frame will count as speech.", exc)
        return AlwaysSpeechDetector()
