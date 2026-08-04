"""
Tests for utterance endpointing.

The detectors are faked so these run in milliseconds and assert the logic
rather than the models: whether a pause splits a sentence, whether the word
onset survives, whether an unfinished-sounding turn is extended. Tests that
need the real ONNX files live in test_models.py and skip without them.
"""

from __future__ import annotations

import numpy as np
import pytest

from endpointing import (
    FRAME_SECONDS,
    SAMPLE_RATE,
    Endpointer,
    EndpointerSettings,
    frames_from_pcm16,
)
from voice_activity import FRAME_SAMPLES


class ScriptedVAD:
    """Speech on the frames you say so, silence everywhere else."""

    def __init__(self, pattern: str) -> None:
        # "S" = speech, "." = silence, one character per frame.
        self.pattern = pattern
        self.index = 0

    def speech_probability(self, frame: np.ndarray) -> float:
        char = self.pattern[self.index] if self.index < len(self.pattern) else "."
        self.index += 1
        return 1.0 if char == "S" else 0.0

    def reset(self) -> None:
        return


class AlwaysComplete:
    def is_complete(self, audio: np.ndarray) -> bool:
        return True


class NeverComplete:
    def is_complete(self, audio: np.ndarray) -> bool:
        return False


class CompleteAfter:
    """Says "unfinished" a fixed number of times, then relents."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.calls = 0

    def is_complete(self, audio: np.ndarray) -> bool:
        self.calls += 1
        return self.calls > self.refusals


def frames(count: int, value: float = 0.5) -> list[np.ndarray]:
    return [np.full(FRAME_SAMPLES, value, dtype=np.float32) for _ in range(count)]


def run(pattern: str, turns=None, settings=None) -> list[bytes]:
    """Drive the endpointer through one frame per character and collect utterances."""
    endpointer = Endpointer(
        ScriptedVAD(pattern),
        turns or AlwaysComplete(),
        settings or EndpointerSettings(preroll_seconds=0.1, hangover_seconds=0.2),
    )
    out = []
    for frame in frames(len(pattern)):
        completed = endpointer.push(frame)
        if completed is not None:
            out.append(completed)
    return out


def seconds(pcm: bytes) -> float:
    return len(pcm) / 2 / SAMPLE_RATE


# ---------------------------------------------------------------------------
# The bug this whole change exists to fix
# ---------------------------------------------------------------------------


def test_short_pause_does_not_split_the_sentence() -> None:
    """
    "What do you want ... to talk about" — one utterance, not two.

    hangover is 0.2s here; the gap is 0.096s (3 frames), so it must survive.
    """
    utterances = run("SSSSSSS...SSSSSSS" + "." * 12)
    assert len(utterances) == 1, f"sentence was split into {len(utterances)} pieces"


def test_real_pause_ends_the_turn() -> None:
    """A gap longer than the hangover is a genuine endpoint."""
    utterances = run("SSSSS" + "." * 10 + "SSSSS" + "." * 10)
    assert len(utterances) == 2


def test_preroll_recovers_the_word_onset() -> None:
    """
    Audio from before speech was detected must be in the utterance.

    Without pre-roll the utterance would start at the first speech frame and
    Whisper would hear a clipped first word.
    """
    settings = EndpointerSettings(preroll_seconds=0.1, hangover_seconds=0.2)
    preroll_frames = round(settings.preroll_seconds / FRAME_SECONDS)

    # 5 frames of silence before speech starts; pre-roll should keep 3 of them.
    utterances = run("....." + "SSSSS" + "." * 10, settings=settings)
    assert len(utterances) == 1

    expected_frames = preroll_frames + 5 + round(settings.hangover_seconds / FRAME_SECONDS)
    assert seconds(utterances[0]) == pytest.approx(expected_frames * FRAME_SECONDS, abs=1e-6)


def test_unfinished_turn_is_extended_then_completed() -> None:
    """
    A turn that sounds unfinished keeps listening, and picks up what follows.

    The detector refuses once, so the trailing speech must land in the same
    utterance rather than becoming a second one.
    """
    turns = CompleteAfter(refusals=1)
    utterances = run("SSSSS" + "." * 8 + "SSSSS" + "." * 8, turns=turns)
    assert turns.calls >= 2
    assert len(utterances) == 1, "extension should have kept this as one utterance"


def test_extension_budget_stops_runaway_turns() -> None:
    """A detector that never says "done" must not hold the turn open forever."""
    settings = EndpointerSettings(
        preroll_seconds=0.1, hangover_seconds=0.2, max_extension_seconds=0.4
    )
    utterances = run("SSSSS" + "." * 60, turns=NeverComplete(), settings=settings)
    assert len(utterances) == 1


def test_max_utterance_length_is_capped() -> None:
    settings = EndpointerSettings(
        preroll_seconds=0.1, hangover_seconds=0.5, max_utterance_seconds=0.5
    )
    utterances = run("S" * 40, settings=settings)
    assert utterances, "the cap should have produced an utterance"
    assert seconds(utterances[0]) <= 0.6


def test_silence_alone_produces_nothing() -> None:
    assert run("." * 40) == []


def test_reset_discards_the_utterance_in_progress() -> None:
    endpointer = Endpointer(ScriptedVAD("S" * 20), AlwaysComplete(), EndpointerSettings())
    for frame in frames(5):
        endpointer.push(frame)
    assert endpointer.in_speech
    endpointer.reset()
    assert not endpointer.in_speech


# ---------------------------------------------------------------------------
# Framing incoming network bytes
# ---------------------------------------------------------------------------


def test_frames_from_pcm16_splits_whole_frames_only() -> None:
    one_and_a_half = b"\x00\x00" * (FRAME_SAMPLES + FRAME_SAMPLES // 2)
    got, carry = frames_from_pcm16(one_and_a_half)
    assert len(got) == 1
    assert len(carry) == FRAME_SAMPLES  # half a frame of bytes, kept for next time


def test_frames_from_pcm16_reassembles_across_reads() -> None:
    """A frame split across two network reads must still come out whole."""
    payload = b"\x01\x02" * FRAME_SAMPLES
    first, carry = frames_from_pcm16(payload[:100])
    assert first == []
    second, carry = frames_from_pcm16(payload[100:], carry)
    assert len(second) == 1
    assert carry == b""


def test_frames_from_pcm16_scales_to_unit_range() -> None:
    loudest = np.full(FRAME_SAMPLES, 32767, dtype=np.int16).tobytes()
    got, _ = frames_from_pcm16(loudest)
    assert got[0].max() == pytest.approx(1.0, abs=1e-4)
