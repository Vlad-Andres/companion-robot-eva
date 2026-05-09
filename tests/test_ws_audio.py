import json

from fastapi.testclient import TestClient

from robot_backend.app import create_app


def _recv_until(ws, predicate, max_messages: int = 20):
    for _ in range(max_messages):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("message not received")


def test_ws_audio_end_emits_commands(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_BACKEND_STT_STUB_TEXT", "turn left")
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws/audio") as ws:
            _recv_until(ws, lambda m: m.get("type") == "hello")
            _recv_until(ws, lambda m: m.get("type") == "status" and m.get("state") == "ready")

            ws.send_bytes(b"\x00\x01" * 100)
            ws.send_text(json.dumps({"type": "audio.end", "utterance_id": "utt_test"}))

            _recv_until(ws, lambda m: m.get("type") == "asr.final" and m.get("utterance_id") == "utt_test")
            _recv_until(ws, lambda m: m.get("type") == "memory.suggest")
            cmd1 = _recv_until(ws, lambda m: m.get("type") == "cmd")
            cmd2 = _recv_until(ws, lambda m: m.get("type") == "cmd")

            names = {cmd1["cmd"]["name"], cmd2["cmd"]["name"]}
            assert names == {"speak", "move_base"}
