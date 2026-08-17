import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from voice_activity import FRAME_SAMPLES

FRAME_BYTES = FRAME_SAMPLES * 2


def _recv_until(websocket, predicate, max_messages: int = 30):
    """Read text frames until `predicate` matches, stepping over audio."""
    for _ in range(max_messages):
        frame = websocket.receive()
        text = frame.get("text")
        if text is None:
            continue  # synthesized speech, not a control message
        message = json.loads(text)
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


def _messages_until_pong(websocket, max_messages: int = 30) -> list[dict]:
    """
    Everything the server sent, up to a round trip.

    Proving a message was *not* sent needs a marker to stop at: receive()
    blocks forever on an empty queue, so "read a few more and hope" hangs the
    suite instead of failing it. A ping is answered after everything already
    queued, so anything the turn was going to send has arrived by then.
    """
    websocket.send_text(json.dumps({"type": "ping"}))
    seen = []
    for _ in range(max_messages):
        frame = websocket.receive()
        text = frame.get("text")
        if text is None:
            continue
        message = json.loads(text)
        if message.get("type") == "pong":
            return seen
        seen.append(message)
    raise AssertionError("no pong came back")


def _declare(websocket, *, actuators, sensors=("microphone",), protocol="eva/1") -> dict:
    """Send a capability manifest and return the server's acknowledgement."""
    websocket.send_text(
        json.dumps(
            {
                "v": "eva/1",
                "type": "capabilities",
                "protocol": [protocol],
                "robot": {"id": "test-01", "name": "test robot"},
                "sensors": list(sensors),
                "actuators": list(actuators),
            }
        )
    )
    return _recv_until(websocket, lambda m: m.get("type") in {"capabilities.ack", "error"})


def test_rule_confirmation_is_spoken_not_sent_as_a_command(
    monkeypatch, deterministic_detectors
) -> None:
    """
    "Turning left." is synthesized here, not shipped to a robot with no voice.

    The rule produces a speak action and a move action. Speech is fulfilled
    by the server, which owns the synthesiser; only the movement travels as
    a command. Sending speak over the wire is how confirmations used to go
    out silently.
    """
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

            speech = _recv_until(websocket, lambda m: m.get("type") == "speech.start")
            assert speech["speech"]["text"] == "Turning left."

            command = _recv_until(websocket, lambda m: m.get("type") == "command")
            assert command["command"]["name"] == "move_base"
            assert command["command"]["args"]["command"] == "turn_left"


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


def test_the_manifest_is_answered_with_what_this_robot_can_be_sent(
    monkeypatch, deterministic_detectors
) -> None:
    """
    The other half of the handshake.

    The robot declares its hardware; the server declares back the exact set of
    commands this session can send it, so anything else arriving is a server
    bug rather than something the robot has to defend against.
    """
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            ack = _declare(websocket, actuators=["base", "speaker", "eyes", "grabber"])

            assert ack["type"] == "capabilities.ack"
            assert ack["protocol"] == "eva/1"
            assert {a["name"] for a in ack["actions"]} == {"speak", "move_base"}
            # Hardware the server has no action for is reported, not rejected.
            assert ack["unknown"] == ["grabber"]


def test_a_robot_without_a_base_is_not_promised_movement(
    monkeypatch, deterministic_detectors
) -> None:
    """
    The same words, a different robot, a different answer.

    "turn left" must not produce "Turning left." from a robot that cannot turn.
    The rule is all or nothing, so the utterance becomes dialogue instead — and
    with the language model off, that means nothing at all.
    """
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            ack = _declare(websocket, actuators=["speaker", "eyes"])
            assert {a["name"] for a in ack["actions"]} == {"speak"}

            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_nobase"}))

            _recv_until(
                websocket,
                lambda m: m.get("type") == "transcript.final" and m.get("utterance_id") == "utt_nobase",
            )

            assert [m for m in _messages_until_pong(websocket) if m.get("type") == "command"] == []


def test_the_model_can_move_the_robot(monkeypatch, deterministic_detectors) -> None:
    """
    The milestone, end to end.

    An utterance no rule matches reaches the language model, whose reply is a
    schema-shaped object; the spoken half is synthesised and the command half
    is validated and sent.
    """
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "could you come over here for a moment")
    monkeypatch.setenv("EVA_LANGUAGE_MODEL_ENABLED", "true")
    monkeypatch.setenv(
        "EVA_LANGUAGE_MODEL_STUB_REPLY",
        json.dumps(
            {
                "say": "Of course, on my way.",
                "commands": [{"name": "move_base", "args": {"command": "come_here"}}],
            }
        ),
    )
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            _declare(websocket, actuators=["base", "speaker"])

            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_llm"}))

            speech = _recv_until(websocket, lambda m: m.get("type") == "speech.start")
            assert speech["speech"]["text"] == "Of course, on my way."

            command = _recv_until(websocket, lambda m: m.get("type") == "command")
            assert command["command"] == {
                **command["command"],
                "name": "move_base",
                "args": {"command": "come_here"},
            }


def test_the_model_cannot_move_a_robot_with_no_base(monkeypatch, deterministic_detectors) -> None:
    """
    Validation is the gate, not the grammar.

    The schema would not have offered `move_base` to this robot at all, but a
    model that emits one anyway — or a stub standing in for one — still gets
    the command dropped rather than forwarded.
    """
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "could you come over here for a moment")
    monkeypatch.setenv("EVA_LANGUAGE_MODEL_ENABLED", "true")
    monkeypatch.setenv(
        "EVA_LANGUAGE_MODEL_STUB_REPLY",
        json.dumps(
            {
                "say": "I would if I could.",
                "commands": [{"name": "move_base", "args": {"command": "come_here"}}],
            }
        ),
    )
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            _declare(websocket, actuators=["speaker"])

            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_nogo"}))

            speech = _recv_until(websocket, lambda m: m.get("type") == "speech.start")
            assert speech["speech"]["text"] == "I would if I could."

            # The turn ends with status ready, so the command would be here by now.
            _recv_until(websocket, lambda m: m.get("type") == "status" and m.get("state") == "ready")
            assert [m for m in _messages_until_pong(websocket) if m.get("type") == "command"] == []


def test_an_undeclared_robot_still_gets_commands(monkeypatch, deterministic_detectors) -> None:
    """Firmware older than the handshake keeps working exactly as it did."""
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)  # and no manifest at all

            websocket.send_bytes(b"\x01\x02" * FRAME_SAMPLES)
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_legacy"}))

            command = _recv_until(websocket, lambda m: m.get("type") == "command")
            assert command["command"]["args"]["command"] == "turn_left"


def test_an_unspeakable_protocol_version_is_refused(monkeypatch, deterministic_detectors) -> None:
    """
    A mismatch stops rather than limps.

    Left connected, the robot would stream audio nobody was going to answer —
    which is much harder to diagnose than being told why.
    """
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _handshake(websocket)
            error = _declare(websocket, actuators=["base"], protocol="eva/9")

            assert error["type"] == "error"
            assert error["error"]["code"] == "protocol_unsupported"


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
