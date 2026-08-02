from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket

from actions import list_actions
from config import load_settings
from language_model import build_language_model_client
from log import configure_logging
from protocol import PROTOCOL_ID
from speech_to_text import build_speech_to_text_engine
from text_to_speech import build_text_to_speech_engine
from websocket_session import run_websocket_session


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings = load_settings()
        app.state.settings = settings
        app.state.speech_to_text = build_speech_to_text_engine(model_name=settings.speech_to_text_model, stub_text=settings.speech_to_text_stub_text)
        app.state.text_to_speech = build_text_to_speech_engine(enabled=settings.text_to_speech_enabled, model_path=settings.piper_model_path, config_path=settings.piper_config_path)
        app.state.language_model = build_language_model_client(
            enabled=settings.language_model_enabled,
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
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
        await run_websocket_session(websocket, settings=app.state.settings, speech_to_text=app.state.speech_to_text, text_to_speech=app.state.text_to_speech, language_model=app.state.language_model)

    return app
