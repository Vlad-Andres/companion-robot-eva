"""
The reflex that keeps Eva off the skirting boards.

This one runs on the Pi and never asks the server anything, so it is the part
of the movement path that still works when the WiFi does not. What it must get
right is subtle: stop before the wall, do not chatter at the threshold, and
never trap the robot somewhere it cannot reverse out of.
"""

from __future__ import annotations

import pytest

from actions.move_base_handler import MoveBaseHandler
from behaviors.motion_safety import MotionSafetyService
from behaviors.obstacle_guard import ObstacleGuard
from config import BaseConfig, EmergencyStopConfig, RangeSensorConfig
from core.event_bus import Event, EventBus
from tests.test_move_base import RecordingDriver


def _guard() -> tuple[ObstacleGuard, MoveBaseHandler, RecordingDriver]:
    driver = RecordingDriver()
    handler = MoveBaseHandler(driver=driver, config=BaseConfig())
    guard = ObstacleGuard(EventBus(), handler, RangeSensorConfig())
    return guard, handler, driver


async def _see(guard: ObstacleGuard, distance_mm: int) -> None:
    await guard._on_range(Event(topic="sensor.range", data=distance_mm, source="test"))


@pytest.mark.asyncio
async def test_a_wall_ahead_stops_a_forward_movement() -> None:
    guard, handler, driver = _guard()
    await handler.execute("forward")
    assert driver.last != (0.0, 0.0)

    await _see(guard, 100)
    assert driver.last == (0.0, 0.0)


@pytest.mark.asyncio
async def test_clearing_the_obstacle_resumes_what_was_asked_for() -> None:
    """
    Held, not cancelled.

    "Forward" was a standing instruction. Once the way is clear it should
    carry on, rather than waiting for a command that already came.
    """
    guard, handler, driver = _guard()
    await handler.execute("forward")
    await _see(guard, 100)
    assert driver.last == (0.0, 0.0)

    await _see(guard, 900)
    left, right = driver.last
    assert left > 0 and right > 0


@pytest.mark.asyncio
async def test_a_reading_at_the_threshold_does_not_chatter() -> None:
    """
    Hysteresis.

    One threshold and a sensor hovering on it would start and stop the motors
    several times a second, which sounds exactly as bad as it is.
    """
    guard, handler, driver = _guard()
    config = RangeSensorConfig()
    await handler.execute("forward")

    await _see(guard, config.stop_distance_mm - 1)
    calls_after_stop = len(driver.calls)

    # Drifting back up, but not yet past the clear threshold.
    for distance in (config.stop_distance_mm + 5, config.stop_distance_mm + 20):
        await _see(guard, distance)

    assert len(driver.calls) == calls_after_stop, "the base was re-commanded inside the hysteresis band"


@pytest.mark.asyncio
async def test_reversing_away_from_a_wall_is_still_allowed() -> None:
    """
    Otherwise the first wall Eva meets is the last place she ever goes.

    An obstacle stop that blocks every direction is not a safety feature, it
    is a trap.
    """
    guard, handler, driver = _guard()
    await handler.execute("forward")
    await _see(guard, 80)

    await handler.execute("backward")
    left, right = driver.last
    assert left < 0 and right < 0

    await handler.execute("turn_left")
    left, right = driver.last
    assert left < 0 < right


@pytest.mark.asyncio
async def test_an_obstacle_does_not_start_a_stopped_robot() -> None:
    """Blocking and clearing while stopped must leave the robot stopped."""
    guard, handler, driver = _guard()

    await _see(guard, 80)
    await _see(guard, 900)

    assert handler.is_moving is False
    assert driver.calls == [] or driver.last == (0.0, 0.0)


@pytest.mark.asyncio
async def test_losing_the_server_stops_a_moving_robot() -> None:
    """
    Not a timeout — a commanded movement is never cut short while the link is
    up. But a robot whose server has vanished cannot be told to stop, so it
    stops itself.
    """
    driver = RecordingDriver()
    handler = MoveBaseHandler(driver=driver, config=BaseConfig())
    safety = MotionSafetyService(EventBus(), handler, EmergencyStopConfig())

    await handler.execute("forward")
    await safety._on_disconnected(Event(topic="perception.backend_disconnected", data=None, source="test"))

    assert driver.last == (0.0, 0.0)
    assert handler.is_moving is False
