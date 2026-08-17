"""
What each spoken movement does to the wheels.

These are the assertions that would otherwise need a robot, a floor and
somebody watching it: that "forward" turns both wheels the same way, that a
turn spins them opposite ways, and that stop means stop.
"""

from __future__ import annotations

import pytest

from actions.move_base_handler import MoveBaseHandler
from config import BaseConfig
from motion.base_driver import BaseDriver


class RecordingDriver(BaseDriver):
    """Remembers every wheel command instead of driving anything."""

    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def drive(self, left: float, right: float) -> None:
        self.calls.append((left, right))

    def stop(self) -> None:
        self.calls.append((0.0, 0.0))

    @property
    def last(self) -> tuple[float, float]:
        return self.calls[-1]


@pytest.fixture
def base() -> tuple[MoveBaseHandler, RecordingDriver]:
    driver = RecordingDriver()
    return MoveBaseHandler(driver=driver, config=BaseConfig()), driver


@pytest.mark.asyncio
async def test_forward_drives_both_wheels_the_same_way(base) -> None:
    handler, driver = base
    await handler.execute("forward")

    left, right = driver.last
    assert left > 0 and right > 0
    assert left == right, "unequal wheels would curve instead of going straight"


@pytest.mark.asyncio
async def test_backward_reverses_both_wheels(base) -> None:
    handler, driver = base
    await handler.execute("backward")

    left, right = driver.last
    assert left < 0 and right < 0


@pytest.mark.asyncio
async def test_turning_spins_the_wheels_against_each_other(base) -> None:
    """
    A round chassis pivots on the spot.

    Turning by slowing one wheel would sweep an arc, which needs floor space
    the robot may not have. Opposite wheels turn within its own footprint.
    """
    handler, driver = base

    await handler.execute("turn_left")
    left, right = driver.last
    assert left < 0 < right

    await handler.execute("turn_right")
    left, right = driver.last
    assert right < 0 < left


@pytest.mark.asyncio
async def test_stop_cuts_both_wheels(base) -> None:
    handler, driver = base
    await handler.execute("forward")
    await handler.execute("stop")

    assert driver.last == (0.0, 0.0)
    assert handler.is_moving is False


@pytest.mark.asyncio
async def test_an_unknown_movement_stops_rather_than_continuing(base) -> None:
    """
    The server validates before sending, so this should be impossible.

    One arriving means the two sides disagree about the vocabulary — and a
    robot that keeps driving on an instruction nobody understood is the worse
    of the two ways to handle that.
    """
    handler, driver = base
    await handler.execute("forward")
    await handler.execute("pirouette")

    assert driver.last == (0.0, 0.0)
    assert handler.is_moving is False


@pytest.mark.asyncio
async def test_come_here_drives_forward(base) -> None:
    """No direction to home in on yet, so it means "towards where I'm facing"."""
    handler, driver = base
    await handler.execute("come_here")

    left, right = driver.last
    assert left > 0 and right > 0


@pytest.mark.asyncio
async def test_a_driver_that_throws_leaves_the_wheels_stopped(base) -> None:
    """A GPIO failure mid-drive must not leave the last command running."""
    handler, _driver = base
    stopped = []

    class BrokenDriver(BaseDriver):
        def drive(self, left, right):
            raise OSError("GPIO went away")

        def stop(self):
            stopped.append(True)

    handler = MoveBaseHandler(driver=BrokenDriver(), config=BaseConfig())
    await handler.execute("forward")

    assert stopped, "a failing drive() must be followed by a stop()"


@pytest.mark.asyncio
async def test_a_command_from_the_server_reaches_the_wheels() -> None:
    """
    The seam this branch exists to close.

    A `move_base` envelope used to reach ServerFeedbackService and stop there
    as a log line. This walks the whole robot-side path — server message, event
    bus, dispatcher, handler, driver — and asserts the wheels actually turned.
    """
    from behaviors.server_feedback import ServerFeedbackService
    from core.action_dispatcher import ActionDispatcher
    from core.event_bus import Event, EventBus

    driver = RecordingDriver()
    handler = MoveBaseHandler(driver=driver, config=BaseConfig())

    dispatcher = ActionDispatcher()
    dispatcher.register_handler(handler)

    feedback = ServerFeedbackService(
        event_bus=EventBus(), action_dispatcher=dispatcher, audio_output=None
    )

    await feedback._on_backend_command(
        Event(
            topic="perception.backend_command",
            data={"id": "command_1", "name": "move_base", "args": {"command": "turn_right"}},
            source="test",
        )
    )

    left, right = driver.last
    assert right < 0 < left, "a turn_right from the server did not turn the wheels"


@pytest.mark.asyncio
async def test_wheel_inversion_is_a_config_change_not_a_rewiring() -> None:
    """A motor wired backwards is fixed in config, not with a screwdriver."""
    from motion.tb6612 import TB6612BaseDriver

    config = BaseConfig()
    config.invert_left = True
    driver = TB6612BaseDriver(config)

    driver.drive(0.5, 0.5)
    # IN1 high means forward on this chip; the inverted side runs the other way.
    assert driver._left._in2.value == 1
    assert driver._right._in1.value == 1
