import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import DecisionAPIConfig, SpeechAPIConfig, VisionAPIConfig
from core.context_manager import ContextManager
from core.event_bus import EventBus
from decision.decision_engine import DecisionEngine
from perception.speech_client import SpeechClient
from perception.vision_client import VisionClient


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""

        if self.path == "/transcribe":
            payload = {"text": "hello"} if body else {"text": ""}
            self._send_json(200, payload)
            return

        if self.path == "/decide":
            try:
                _ = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                self._send_json(400, {"error": "bad json"})
                return
            self._send_json(
                200,
                {"actions": [{"type": "speak", "payload": {"text": "ok"}}]},
            )
            return

        if self.path == "/recognize":
            self._send_json(
                200,
                {"objects": [{"label": "cup", "position": {"x": 1, "y": 2, "width": 3, "height": 4}, "confidence": 0.9}]},
            )
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class APIClientTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        host, port = cls.httpd.server_address
        cls.base_url = f"http://{host}:{port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    async def test_speech_client_calls_api(self) -> None:
        bus = EventBus()
        ctx = ContextManager()
        cfg = SpeechAPIConfig(base_url=self.base_url, endpoint="/transcribe", timeout_seconds=2.0, enabled=True)
        client = SpeechClient(bus, ctx, cfg)
        text = await client._call_api(b"\x00\x10" * 1000)
        self.assertEqual(text, "hello")

    async def test_decision_engine_calls_api(self) -> None:
        bus = EventBus()
        ctx = ContextManager()
        cfg = DecisionAPIConfig(base_url=self.base_url, endpoint="/decide", timeout_seconds=2.0, enabled=True)
        engine = DecisionEngine(bus, ctx, cfg)
        result = await engine._call_llm_api({"hello": "world"})
        self.assertIn("actions", result)
        self.assertEqual(result["actions"][0]["type"], "speak")

    async def test_vision_client_calls_api(self) -> None:
        bus = EventBus()
        ctx = ContextManager()
        cfg = VisionAPIConfig(base_url=self.base_url, endpoint="/recognize", timeout_seconds=2.0, enabled=True)
        client = VisionClient(bus, ctx, cfg)
        objects = await client._call_api(b"fake-image-bytes")
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].label, "cup")


if __name__ == "__main__":
    unittest.main()

