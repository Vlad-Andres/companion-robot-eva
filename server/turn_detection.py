"""
turn_detection.py — Has the speaker actually finished?

Silence alone cannot answer this. "What do you want to talk about" and "What
do you want to—" are followed by the same silence; only the sound of the words
before it says whether more is coming.

Smart Turn v3 judges that from the waveform rather than the transcript, so it
does not have to wait for speech-to-text. It reads the last 8 seconds as
Whisper mel features and returns P(the turn is complete).
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

import numpy as np

from log import logger

_log = logger("eva.turn_detection")

SAMPLE_RATE = 16000
WINDOW_SECONDS = 8
WINDOW_SAMPLES = SAMPLE_RATE * WINDOW_SECONDS


class TurnDetector(Protocol):
    """Decides whether a pause is the end of a turn or a thinking pause."""

    def is_complete(self, audio: np.ndarray) -> bool:
        """True if `audio` (float32, 16 kHz) sounds like a finished turn."""
        ...


class SmartTurnDetector:
    """Smart Turn v3 over onnxruntime."""

    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        import onnxruntime
        from faster_whisper.feature_extractor import FeatureExtractor

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1

        self._session = onnxruntime.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        # chunk_length=8 gives the 80 x 800 mel the model was exported for.
        self._features = FeatureExtractor(chunk_length=WINDOW_SECONDS)
        self._threshold = threshold

    def probability(self, audio: np.ndarray) -> float:
        """P(turn complete) for the tail of `audio`."""
        tail = audio[-WINDOW_SAMPLES:].astype(np.float32)

        # The model is trained with the speech at the end of the window and
        # zeros before it, so short clips are padded on the left.
        window = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
        window[WINDOW_SAMPLES - len(tail):] = tail

        mel = self._features(window, padding=0)[None].astype(np.float32)
        logit = float(self._session.run(None, {"input_features": mel})[0][0][0])
        return 1.0 / (1.0 + np.exp(-logit))

    def is_complete(self, audio: np.ndarray) -> bool:
        probability = self.probability(audio)
        _log.debug("turn complete probability %.3f", probability)
        return probability >= self._threshold


class SilenceOnlyTurnDetector:
    """Every pause ends the turn — the behaviour before Smart Turn existed."""

    def is_complete(self, audio: np.ndarray) -> bool:
        return True


def build_turn_detector(*, enabled: bool, model_path: str, threshold: float) -> TurnDetector:
    if not enabled:
        _log.info("Turn detection: silence only (semantic detection disabled)")
        return SilenceOnlyTurnDetector()

    if not os.path.exists(model_path):
        _log.warning(
            "Smart Turn model not found at %s — falling back to silence only. "
            "Fetch it with: make models",
            model_path,
        )
        return SilenceOnlyTurnDetector()

    try:
        detector = SmartTurnDetector(model_path, threshold=threshold)
        _log.info("Turn detection: smart-turn (%s)", os.path.basename(model_path))
        return detector
    except Exception as exc:
        _log.warning("Could not load Smart Turn (%s) — falling back to silence only.", exc)
        return SilenceOnlyTurnDetector()
