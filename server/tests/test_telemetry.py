"""
Tests for the debug telemetry and its dashboard.

Also pins the property that made a missing import cost an afternoon: if the
audio loop raises, it must say so rather than going quiet.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from telemetry import DebugTelemetry, NullTelemetry, build_telemetry
from voice_activity import FRAME_SAMPLES
from websocket_session import report_audio_task_failure


def test_disabled_by_default() -> None:
    telemetry = build_telemetry(enabled=False)
    assert isinstance(telemetry, NullTelemetry)
    assert telemetry.enabled is False


def test_null_telemetry_costs_nothing_and_swallows_everything() -> None:
    telemetry = NullTelemetry()
    telemetry.emit("anything", a=1)
    telemetry.frame(rms=0.5, speech_probability=0.9, in_speech=True)
    with telemetry.timed("stt"):
        pass  # must be a working context manager, not just an attribute


@pytest.mark.asyncio
async def test_events_reach_every_subscriber() -> None:
    telemetry = DebugTelemetry()
    first, second = telemetry.subscribe(), telemetry.subscribe()

    telemetry.frame(rms=0.25, speech_probability=0.98, in_speech=True)

    for queue in (first, second):
        event = queue.get_nowait()
        assert event["type"] == "frame"
        assert event["p"] == 0.98
        assert event["speech"] is True
        assert "t" in event

    telemetry.unsubscribe(first)
    telemetry.emit("state", state="idle")
    assert first.empty()
    assert not second.empty()


@pytest.mark.asyncio
async def test_a_stalled_dashboard_cannot_block_the_pipeline() -> None:
    """
    The whole point of the queue. A tab that stops reading must be dropped
    frames, not allowed to apply backpressure to the audio loop.
    """
    telemetry = DebugTelemetry()
    queue = telemetry.subscribe()

    for _ in range(5000):
        telemetry.frame(rms=0.1, speech_probability=0.1, in_speech=False)

    assert queue.full()
    assert queue.qsize() <= 256


@pytest.mark.asyncio
async def test_timed_reports_the_stage() -> None:
    telemetry = DebugTelemetry()
    queue = telemetry.subscribe()

    with telemetry.timed("stt"):
        await asyncio.sleep(0.02)

    event = queue.get_nowait()
    assert event["type"] == "stage"
    assert event["stage"] == "stt"
    assert event["ms"] >= 15


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_dashboard_is_absent_unless_enabled(monkeypatch) -> None:
    monkeypatch.setenv("EVA_DEBUG_ENABLED", "false")
    with TestClient(create_app()) as client:
        assert client.get("/debug").status_code == 404


def test_dashboard_is_served_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("EVA_DEBUG_ENABLED", "true")
    with TestClient(create_app()) as client:
        page = client.get("/debug")
        assert page.status_code == 200
        assert "/v1/websocket/debug" in page.text


def test_dashboard_receives_frames_while_speaking(monkeypatch) -> None:
    """End to end: audio in on one socket, telemetry out on the other."""
    monkeypatch.setenv("EVA_DEBUG_ENABLED", "true")
    monkeypatch.setenv("EVA_VAD_MODEL_PATH", "models/does-not-exist.onnx")
    monkeypatch.setenv("EVA_TURN_DETECTION_ENABLED", "false")
    monkeypatch.setenv("EVA_SPEECH_TO_TEXT_STUB_TEXT", "hello")

    with TestClient(create_app()) as client:
        with client.websocket_connect("/v1/websocket/debug") as debug:
            assert debug.receive_json()["type"] == "config"

            with client.websocket_connect("/v1/websocket/audio") as audio:
                audio.receive_json()  # hello
                audio.receive_json()  # status: ready
                for _ in range(4):
                    audio.send_bytes(b"\x20\x10" * FRAME_SAMPLES)

                for _ in range(30):
                    event = debug.receive_json()
                    if event["type"] == "frame":
                        assert 0.0 <= event["p"] <= 1.0
                        assert event["rms"] > 0
                        return
                raise AssertionError("no frame telemetry arrived")


@pytest.mark.asyncio
async def test_a_dead_audio_loop_is_reported(caplog) -> None:
    """
    A crash in the audio task used to leave the session silently deaf: audio
    still arriving, nothing processing it, nothing logged. It must complain.
    """
    async def boom() -> None:
        raise RuntimeError("boom")

    task = asyncio.get_running_loop().create_task(boom())
    with pytest.raises(RuntimeError):
        await task

    with caplog.at_level("ERROR"):
        report_audio_task_failure(task)

    assert any("Audio loop stopped" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_audio_loop_is_not_an_error(caplog) -> None:
    """Normal shutdown cancels the task; that must not look like a failure."""
    async def forever() -> None:
        await asyncio.sleep(3600)

    task = asyncio.get_running_loop().create_task(forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with caplog.at_level("ERROR"):
        report_audio_task_failure(task)

    assert not [r for r in caplog.records if "Audio loop stopped" in r.message]
