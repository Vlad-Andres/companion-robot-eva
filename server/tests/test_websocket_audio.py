import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from voice_activity import FRAME_SAMPLES

FRAME_BYTES = FRAME_SAMPLES * 2


def _recv_until(websocket, predicate, max_messages: int = 30):
    for _ in range(max_messages):
        message = websocket.receive_json()
        if predicate(message):
            return message
    raise AssertionError("message not received")


@pytest.fixture
def deterministic_detectors(monkeypatch):
    """
    Swap the ONNX models out for their always-on fallbacks.

    Pointing the VAD at a path that does not exist selects
    AlwaysSpeechDetector, so every frame counts as speech and these tests
    exercise the session without depending on model files or real audio.
    """
    monkeypatch.setenv("EVA_VAD_MODEL_PATH", "models/does-not-exist.onnx")
    monkeypatch.setenv("EVA_TURN_DETECTION_ENABLED", "false")


def _handshake(websocket) -> None:
    _recv_until(websocket, lambda m: m.get("type") == "hello")
    _recv_until(websocket, lambda m: m.get("type") == "status" and m.get("state") == "ready")


def test_audio_end_finalizes_and_emits_commands(monkeypatch, deterministic_detectors) -> None:
    """An explicit audio.end flushes whatever has been captured."""
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)

            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)  # one whole frame
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_test"}))

            _recv_until(
                websocket,
                lambda m: m.get("type") == "transcript.final" and m.get("utterance_id") == "utt_test",
            )
            first = _recv_until(websocket, lambda m: m.get("type") == "command")
            second = _recv_until(websocket, lambda m: m.get("type") == "command")

            assert {first["command"]["name"], second["command"]["name"]} == {"speak", "move_base"}


def test_endpointer_finalizes_without_audio_end(monkeypatch, deterministic_detectors) -> None:
    """
    The robot never has to say when a turn ended.

    This is the path that replaced the idle timer: the server decides from
    the audio alone. Here the utterance cap is what closes it, since the
    fallback detector never reports silence.
    """
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "hello there")
    monkeypatch.setenv("EVA_MAX_UTTERANCE_SECONDS", "0.1")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)

            # 0.1s cap at 32ms per frame: a handful of frames is plenty.
            for _ in range(8):
                websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)

            message = _recv_until(websocket, lambda m: m.get("type") == "transcript.final")
            assert message["text"] == "hello there"


def test_speech_onset_is_announced(monkeypatch, deterministic_detectors) -> None:
    """The robot is told when speech starts, so its eyes react to speech."""
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "hello")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)

            _recv_until(
                websocket,
                lambda m: m.get("type") == "status" and m.get("state") == "listening",
            )


def test_partial_frames_are_reassembled(monkeypatch, deterministic_detectors) -> None:
    """A frame split across two sends must not be lost or corrupted."""
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)

            payload = b"\x01\x02" * FRAME_SAMPLES
            websocket.send_bytes(payload[: FRAME_BYTES // 3])
            websocket.send_bytes(payload[FRAME_BYTES // 3 :])
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_split"}))

            _recv_until(
                websocket,
                lambda m: m.get("type") == "transcript.final" and m.get("utterance_id") == "utt_split",
            )
