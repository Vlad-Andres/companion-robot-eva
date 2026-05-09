from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket

from .actions import list_actions
from .config import load_settings
from .llm import build_default_llm_client
from .log import configure_logging
from .protocol import PROTOCOL_ID
from .stt import build_default_stt_engine
from .tts import build_default_tts_engine
from .ws import run_ws_session


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        settings = load_settings()
        app.state.settings = settings
        app.state.stt = build_default_stt_engine(model_name=settings.stt_model, stub_text=settings.stt_stub_text)
        app.state.tts = build_default_tts_engine(enabled=settings.tts_enabled, model_path=settings.piper_model_path, config_path=settings.piper_config_path)
        app.state.llm = build_default_llm_client(
            enabled=settings.llm_enabled,
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

    @app.websocket("/v1/ws/audio")
    async def ws_audio(ws: WebSocket) -> None:
        await run_ws_session(ws, settings=app.state.settings, stt=app.state.stt, tts=app.state.tts, llm=app.state.llm)

    return app
