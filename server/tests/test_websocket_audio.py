import json

from fastapi.testclient import TestClient

from app import create_app


def _recv_until(websocket, predicate, max_messages: int = 20):
    for _ in range(max_messages):
        message = websocket.receive_json()
        if predicate(message):
            return message
    raise AssertionError("message not received")


def test_ws_audio_end_emits_commands(monkeypatch) -> None:
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/websocket/audio") as websocket:
            _recv_until(websocket, lambda m: m.get("type") == "hello")
            _recv_until(websocket, lambda m: m.get("type") == "status" and m.get("state") == "ready")

            websocket.send_bytes(b"\x00\x01" * 100)
            websocket.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_test"}))

            _recv_until(websocket, lambda m: m.get("type") == "transcript.final" and m.get("utterance_id") == "utt_test")
            _recv_until(websocket, lambda m: m.get("type") == "memory.suggest")
            command1 = _recv_until(websocket, lambda m: m.get("type") == "command")
            command2 = _recv_until(websocket, lambda m: m.get("type") == "command")

            names = {command1["command"]["name"], command2["command"]["name"]}
            assert names == {"speak", "move_base"}
