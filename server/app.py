from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket

from actions import list_actions
from config import load_settings
from dataset_recorder import DatasetSettings, build_dataset_recorder
from language_model import build_language_model_client
from log import configure_logging
from protocol import PROTOCOL_ID
from speech_to_text import build_speech_to_text_engine
from text_to_speech import build_text_to_speech_engine
from turn_detection import build_turn_detector
from voice_activity import build_voice_activity_detector
from websocket_session import run_websocket_session


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings = load_settings()
        app.state.settings = settings
        app.state.speech_to_text = build_speech_to_text_engine(model_name=settings.speech_to_text_model, stub_text=settings.speech_to_text_stub_text)
        app.state.text_to_speech = build_text_to_speech_engine(
            enabled=settings.text_to_speech_enabled,
            model_path=settings.piper_model_path,
            config_path=settings.piper_config_path,
            engine=settings.text_to_speech_engine,
        )
        app.state.language_model = build_language_model_client(
            enabled=settings.language_model_enabled,
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            max_reply_tokens=settings.ollama_max_reply_tokens,
            keep_alive=settings.ollama_keep_alive,
        )
        app.state.dataset_recorder = build_dataset_recorder(
            DatasetSettings(
                enabled=settings.dataset_capture_enabled,
                directory=settings.dataset_directory,
                max_bytes=settings.dataset_max_bytes,
            )
        )
        # Loaded once and shared; each session gets its own Endpointer around
        # them, since only the endpointer keeps per-connection state.
        app.state.voice_activity = build_voice_activity_detector(settings.voice_activity_model_path)
        app.state.turn_detector = build_turn_detector(
            enabled=settings.turn_detection_enabled,
            model_path=settings.turn_detection_model_path,
            threshold=settings.turn_detection_threshold,
        )
        yield

    app = FastAPI(title="Robot Backend", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/v1/protocol")
    async def protocol() -> dict[str, Any]:
        return {"protocol": PROTOCOL_ID}

    @app.get("/v1/actions")
    async def actions() -> dict[str, Any]:
        return {"actions": list_actions()}

    @app.websocket("/v1/websocket/audio")
    async def websocket_audio(websocket: WebSocket) -> None:
        await run_websocket_session(
            websocket,
            settings=app.state.settings,
            speech_to_text=app.state.speech_to_text,
            text_to_speech=app.state.text_to_speech,
            language_model=app.state.language_model,
            dataset_recorder=app.state.dataset_recorder,
            voice_activity=app.state.voice_activity,
            turn_detector=app.state.turn_detector,
        )

    return app
