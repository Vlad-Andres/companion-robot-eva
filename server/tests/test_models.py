"""
Tests that run the real ONNX models.

These need `make models` and, for the speech fixtures, macOS `say`. They skip
rather than fail when either is missing, so the suite still runs on a bare
checkout — but when they do run they are the ones that prove the pipeline
handles the sentence that used to get cut in half.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import wave

import numpy as np
import pytest

from endpointing import SAMPLE_RATE, Endpointer, EndpointerSettings, frames_from_pcm16
from turn_detection import SmartTurnDetector
from voice_activity import SileroVoiceActivityDetector

MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
VAD_MODEL = os.path.join(MODELS, "silero_vad.onnx")
TURN_MODEL = os.path.join(MODELS, "smart_turn.onnx")

needs_vad = pytest.mark.skipif(not os.path.exists(VAD_MODEL), reason="run: make models")
needs_turn = pytest.mark.skipif(not os.path.exists(TURN_MODEL), reason="run: make models")
needs_say = pytest.mark.skipif(shutil.which("say") is None, reason="needs macOS `say`")


@pytest.fixture(scope="module")
def vad() -> SileroVoiceActivityDetector:
    return SileroVoiceActivityDetector(VAD_MODEL)


def speak(text: str, tmp_path) -> np.ndarray:
    """Synthesize `text` to float32 16 kHz mono."""
    path = str(tmp_path / "speech.wav")
    subprocess.run(
        ["say", "-o", path, "--data-format=LEI16@16000", "--channels=1", text], check=True
    )
    with wave.open(path, "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def push_all(endpointer: Endpointer, audio: np.ndarray) -> list[bytes]:
    pcm = (audio * 32767).astype(np.int16).tobytes()
    frames, _ = frames_from_pcm16(pcm)
    return [done for f in frames if (done := endpointer.push(f)) is not None]


# ---------------------------------------------------------------------------


@needs_vad
@needs_say
def test_silero_hears_speech_and_ignores_loud_noise(vad, tmp_path) -> None:
    """
    The whole reason for replacing the RMS gate.

    Loud random noise has a high RMS and would have opened an energy gate
    wide; Silero has to score it far below real speech.
    """
    speech = speak("Hello there, this is Eva speaking.", tmp_path)
    noise = (np.random.default_rng(0).standard_normal(len(speech)) * 0.3).astype(np.float32)

    def speech_fraction(audio: np.ndarray) -> float:
        vad.reset()
        frames, _ = frames_from_pcm16((audio * 32767).astype(np.int16).tobytes())
        hits = sum(vad.speech_probability(f) >= 0.5 for f in frames)
        return hits / max(len(frames), 1)

    assert speech_fraction(speech) > 0.5
    assert speech_fraction(noise) < 0.1


@needs_vad
@needs_say
def test_the_sentence_that_used_to_get_cut(vad, tmp_path) -> None:
    """
    Regression test for the original complaint.

    "What do you want to talk about" was arriving as "what do you want"
    because the server's 0.9s idle timer expired between 1.5s chunks. The
    endpointer must return it as exactly one utterance, no shorter than the
    speech itself.
    """
    audio = speak("What do you want to talk about", tmp_path)
    assert len(audio) / SAMPLE_RATE > 1.5, "fixture must outlast the old 1.5s chunk"

    endpointer = Endpointer(vad, _AlwaysComplete(), EndpointerSettings())
    utterances = push_all(endpointer, np.concatenate([audio, np.zeros(SAMPLE_RATE, np.float32)]))

    assert len(utterances) == 1, f"sentence split into {len(utterances)} pieces"
    captured = len(utterances[0]) / 2 / SAMPLE_RATE
    assert captured >= len(audio) / SAMPLE_RATE * 0.9, "utterance is missing speech"


@needs_vad
@needs_say
def test_preroll_keeps_the_first_word(vad, tmp_path) -> None:
    """The utterance must start before the first frame Silero flagged."""
    audio = speak("Turn left", tmp_path)
    padded = np.concatenate(
        [np.zeros(SAMPLE_RATE // 2, np.float32), audio, np.zeros(SAMPLE_RATE, np.float32)]
    )

    settings = EndpointerSettings(preroll_seconds=0.3)
    endpointer = Endpointer(vad, _AlwaysComplete(), settings)
    utterances = push_all(endpointer, padded)

    assert len(utterances) == 1
    # Speech is ~0.5s in; with 0.3s of pre-roll the utterance must begin earlier.
    assert len(utterances[0]) / 2 / SAMPLE_RATE > len(audio) / SAMPLE_RATE + 0.2


@needs_turn
@needs_say
def test_smart_turn_separates_finished_from_unfinished(tmp_path) -> None:
    """A trailing "to" should score lower than a completed phrase."""
    detector = SmartTurnDetector(TURN_MODEL)
    complete = detector.probability(speak("What do you want to talk about", tmp_path))
    incomplete = detector.probability(speak("What do you want to", tmp_path))
    assert complete > incomplete


@needs_vad
@needs_say
def test_real_speech_through_the_real_session(monkeypatch, tmp_path) -> None:
    """
    Integration: real speech, real Silero, real socket, robot-sized frames.

    This asserts the pieces fit together and a turn completes on silence
    alone, with no audio.end and no timer. That a sentence is not *split* is
    asserted deterministically at the endpointer level in
    test_the_sentence_that_used_to_get_cut — counting messages here would
    race the audio task against the receive loop.
    """
    from fastapi.testclient import TestClient

    from app import create_app

    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "what do you want to talk about")
    monkeypatch.setenv("EVA_TURN_DETECTION_ENABLED", "false")  # silence alone: strictest case
    monkeypatch.setenv("EVA_LANGUAGE_MODEL_ENABLED", "false")

    audio = speak("What do you want to talk about", tmp_path)
    assert len(audio) / SAMPLE_RATE > 1.5, "fixture must outlast the old 1.5s chunk period"
    padded = np.concatenate([audio, np.zeros(SAMPLE_RATE, dtype=np.float32)])
    pcm = (padded * 32767).astype(np.int16).tobytes()

    app = create_app()
    frame_bytes = 512 * 2

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            websocket.receive_json()  # hello
            websocket.receive_json()  # status: ready

            for offset in range(0, len(pcm) - frame_bytes, frame_bytes):
                websocket.send_bytes(pcm[offset:offset + frame_bytes])

            # The trailing silence must produce this on its own.
            message = _recv_until(websocket, lambda m: m.get("type") == "transcript.final")
            assert message["text"] == "what do you want to talk about"


def _recv_until(websocket, predicate, max_messages: int = 40):
    for _ in range(max_messages):
        message = websocket.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message never arrived")


class _AlwaysComplete:
    def is_complete(self, audio: np.ndarray) -> bool:
        return True
