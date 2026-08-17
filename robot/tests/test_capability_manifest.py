"""
What the robot claims it can do, and why it must be the truth.

The server builds the language model's output schema from this manifest. Claim
a base that isn't there and Eva will cheerfully say she is on her way, then sit
still — which is a worse failure than not offering to move at all.
"""

from __future__ import annotations

import asyncio

import pytest

from config import RobotConfig
from runtime import RobotRuntime


def _runtime(**overrides) -> RobotRuntime:
    config = RobotConfig()
    config.speech_api.enabled = False
    for key, value in overrides.items():
        setattr(config.base, key, value)
    return RobotRuntime(config)


def test_a_working_base_is_declared() -> None:
    runtime = _runtime(enabled=True)
    manifest = runtime.capability_manifest()

    assert runtime.base_driver.available is True
    assert "base" in manifest["actuators"]
    assert "speaker" in manifest["actuators"]
    assert manifest["sensors"] == ["microphone"]


def test_a_base_turned_off_in_config_is_not_declared() -> None:
    runtime = _runtime(enabled=False)

    assert runtime.base_driver.available is False
    assert "base" not in runtime.capability_manifest()["actuators"]


def test_a_base_that_fails_to_initialise_is_not_declared(monkeypatch) -> None:
    """
    Configured and working are different things.

    `base.enabled` is a request; the manifest answers with what actually came
    up. A pin already in use, a missing library, no GPIO at all — each one
    means this robot cannot move, and saying so is what stops Eva promising to
    come over and then sitting still.
    """
    import gpiozero

    def _refuse(*_args, **_kwargs):
        raise OSError("GPIO busy")

    monkeypatch.setattr(gpiozero, "PWMOutputDevice", _refuse)

    runtime = _runtime(enabled=True)

    assert runtime.base_driver.available is False
    assert "base" not in runtime.capability_manifest()["actuators"]


def test_the_manifest_is_the_shape_the_server_parses() -> None:
    manifest = _runtime().capability_manifest()

    assert manifest["type"] == "capabilities"
    assert manifest["protocol"] == ["eva/1"]
    assert manifest["audio"]["sample_rate_hz"] == 16000
    assert manifest["audio"]["encoding"] == "pcm_s16le"


@pytest.mark.asyncio
async def test_shutdown_stops_the_wheels() -> None:
    """A Ctrl+C that leaves the motors running is the shutdown bug that hurts."""
    runtime = _runtime()
    stopped = asyncio.Event()

    async def _record() -> None:
        stopped.set()

    runtime.move_base.stop = _record  # type: ignore[method-assign]
    await runtime._shutdown()

    assert stopped.is_set()
