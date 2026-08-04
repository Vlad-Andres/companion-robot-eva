"""
endpointing.py — Deciding where one utterance ends and the next begins.

The robot streams every frame it captures and makes no judgements. All the
deciding happens here, which is the point: audio that was never discarded can
still be recovered, so the moment speech is detected we can reach *backwards*
into the ring buffer and recover the word onset that has already gone past.
That is what stops Eva hearing "urn left" when you said "turn left".

A turn ends when speech stops for `hangover` and the turn detector agrees the
sentence sounds finished. If it sounds unfinished, the window is extended and
we keep listening — a thinking pause no longer cuts you off.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from log import logger
from turn_detection import TurnDetector
from voice_activity import FRAME_SAMPLES, VoiceActivityDetector

_log = logger("eva.endpointing")

SAMPLE_RATE = 16000
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE  # 0.032


@dataclass(frozen=True)
class EndpointerSettings:
    speech_threshold: float = 0.5       # P(speech) above which a frame counts
    preroll_seconds: float = 0.3        # audio kept from before speech started
    hangover_seconds: float = 0.6       # silence that provisionally ends a turn
    max_extension_seconds: float = 4.0  # how long an "unfinished" turn may run on
    max_utterance_seconds: float = 30.0 # hard cap; Whisper's own window


class Endpointer:
    """
    Turns a stream of fixed-size frames into complete utterances.

    Feed every frame to push(). It returns the finished utterance as PCM bytes
    on the frame that completes it, and None the rest of the time.
    """

    def __init__(
        self,
        voice_activity: VoiceActivityDetector,
        turn_detector: TurnDetector,
        settings: Optional[EndpointerSettings] = None,
    ) -> None:
        self._vad = voice_activity
        self._turns = turn_detector
        self.settings = settings or EndpointerSettings()

        preroll_frames = max(1, round(self.settings.preroll_seconds / FRAME_SECONDS))
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_frames)

        self._speech: list[np.ndarray] = []
        self._in_speech = False
        self._silent_frames = 0
        self._extended_seconds = 0.0

    # ------------------------------------------------------------------
    # State the session reports to the robot
    # ------------------------------------------------------------------

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def flush(self) -> Optional[bytes]:
        """
        End the current utterance now, whatever the detectors think.

        For an explicit `audio.end` from the robot, which outranks any
        judgement made here. Returns None if nothing is in progress.
        """
        if not self._in_speech or not self._speech:
            return None
        return self._finish()

    def reset(self) -> None:
        """Abandon any utterance in progress — used when the robot is muted."""
        self._speech.clear()
        self._preroll.clear()
        self._in_speech = False
        self._silent_frames = 0
        self._extended_seconds = 0.0
        self._vad.reset()

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    def push(self, frame: np.ndarray) -> Optional[bytes]:
        """
        Feed one frame of float32 audio.

        Returns the completed utterance as 16-bit PCM bytes, or None.
        """
        is_speech = self._vad.speech_probability(frame) >= self.settings.speech_threshold

        if not self._in_speech:
            self._preroll.append(frame)
            if is_speech:
                self._begin_utterance()
            return None

        self._speech.append(frame)
        self._silent_frames = 0 if is_speech else self._silent_frames + 1

        if self._duration_seconds() >= self.settings.max_utterance_seconds:
            _log.info("Utterance hit the %.0fs cap — cutting.", self.settings.max_utterance_seconds)
            return self._finish()

        if self._silent_frames * FRAME_SECONDS < self.settings.hangover_seconds:
            return None

        return self._on_hangover_elapsed()

    def _begin_utterance(self) -> None:
        # Everything still in the ring buffer predates the detection, so it
        # holds the beginning of the word that triggered it.
        self._speech = list(self._preroll)
        self._preroll.clear()
        self._in_speech = True
        self._silent_frames = 0
        self._extended_seconds = 0.0

    def _on_hangover_elapsed(self) -> Optional[bytes]:
        """Silence has lasted long enough. Ask whether the turn really ended."""
        if self._extended_seconds >= self.settings.max_extension_seconds:
            _log.debug("Extension budget spent — ending the turn.")
            return self._finish()

        if self._turns.is_complete(self._audio()):
            return self._finish()

        # Sounds unfinished — keep the microphone open and let them continue.
        self._extended_seconds += self._silent_frames * FRAME_SECONDS
        self._silent_frames = 0
        _log.debug("Turn sounds unfinished — extending (%.1fs used).", self._extended_seconds)
        return None

    def _finish(self) -> bytes:
        audio = self._audio()
        self._speech.clear()
        self._in_speech = False
        self._silent_frames = 0
        self._extended_seconds = 0.0
        _log.info("Utterance complete: %.2fs", len(audio) / SAMPLE_RATE)
        return _to_pcm16(audio)

    # ------------------------------------------------------------------

    def _audio(self) -> np.ndarray:
        if not self._speech:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._speech)

    def _duration_seconds(self) -> float:
        return len(self._speech) * FRAME_SECONDS


def _to_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def frames_from_pcm16(data: bytes, carry: bytes = b"") -> tuple[list[np.ndarray], bytes]:
    """
    Split incoming PCM bytes into whole frames.

    Network reads do not respect frame boundaries, so whatever is left over is
    returned to be prepended to the next read.
    """
    buffer = carry + data
    frame_bytes = FRAME_SAMPLES * 2
    usable = len(buffer) - (len(buffer) % frame_bytes)
    if usable <= 0:
        return [], buffer

    samples = np.frombuffer(buffer[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    frames = [samples[i:i + FRAME_SAMPLES] for i in range(0, len(samples), FRAME_SAMPLES)]
    return frames, buffer[usable:]
