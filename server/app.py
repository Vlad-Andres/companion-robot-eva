from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

from actions import list_actions
from capabilities import SUPPORTED_PROTOCOLS
from config import load_settings
from dataset_recorder import DatasetSettings, build_dataset_recorder
from language_model import build_language_model_client
from log import configure_logging
from protocol import PROTOCOL_ID
from speech_to_text import build_speech_to_text_engine
from telemetry import build_telemetry
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
            temperature=settings.ollama_temperature,
            stub_reply=settings.language_model_stub_reply,
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
        app.state.telemetry = build_telemetry(enabled=settings.debug_enabled)
        yield

    app = FastAPI(title="Robot Backend", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/v1/protocol")
    async def protocol() -> dict[str, Any]:
        return {"protocol": PROTOCOL_ID, "supported_protocols": list(SUPPORTED_PROTOCOLS)}

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
            telemetry=app.state.telemetry,
        )

    # ------------------------------------------------------------------
    # Debug dashboard — only mounted when EVA_DEBUG_ENABLED is on
    # ------------------------------------------------------------------

    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page() -> HTMLResponse:
        if not app.state.settings.debug_enabled:
            return HTMLResponse("Debug is off. Set EVA_DEBUG_ENABLED=true and restart.", status_code=404)
        page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_dashboard.html")
        with open(page, "r", encoding="utf-8") as handle:
            return HTMLResponse(handle.read())

    @app.websocket("/v1/websocket/debug")
    async def websocket_debug(websocket: WebSocket) -> None:
        telemetry = app.state.telemetry
        if not telemetry.enabled:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        settings = app.state.settings
        await websocket.send_json({
            "type": "config",
            "vad_threshold": settings.endpointer.speech_threshold,
            "hangover": settings.endpointer.hangover_seconds,
            "preroll": settings.endpointer.preroll_seconds,
        })

        queue = telemetry.subscribe()
        try:
            while True:
                await websocket.send_json(await queue.get())
        except Exception:
            pass
        finally:
            telemetry.unsubscribe(queue)

    return app
