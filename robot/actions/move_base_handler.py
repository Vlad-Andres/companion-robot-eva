"""
actions/move_base_handler.py — Movement commands become wheel speeds.

This is the one place that knows what "forward" means in wheel terms, and the
one place that holds the base's current motion. Everything else — the server,
the obstacle reflex, the emergency stop — asks it to change that motion rather
than touching the driver.

Motion is latched. `forward` means keep going, not go a bit; the base runs
until something stops it, which is exactly how it was asked for: a `stop`
command, an obstacle, a lost connection, or the button. That is why the
current movement is remembered here — an obstacle that clears has to know
whether it was interrupting anything.
"""

from __future__ import annotations

import asyncio

from actions.action_types import Action
from actions.base_action_handler import BaseActionHandler
from motion.base_driver import BaseDriver
from utils.logger import get_logger

log = get_logger(__name__)

STOP = "stop"

#: Movements that carry the robot forwards, and so are the ones an obstacle in
#: front has any business refusing. Reversing and turning stay available — an
#: obstacle stop that also blocked those would park the robot against a wall
#: with no way to leave it.
FORWARD_COMMANDS = frozenset({"forward", "come_here"})


class MoveBaseHandler(BaseActionHandler):
    """Executes `move_base` against the wheels."""

    action_type = "move_base"

    def __init__(self, driver: BaseDriver, config) -> None:
        """
        Args:
            driver: the base driver — real or null, this class cannot tell.
            config: a BaseConfig, for the two speeds.
        """
        self._driver = driver
        self._config = config
        self._lock = asyncio.Lock()
        self._current = STOP
        self._blocked = False

    @property
    def current_command(self) -> str:
        """What the base is doing right now, as a movement name."""
        return self._current

    @property
    def is_moving(self) -> bool:
        return self._current != STOP

    async def handle(self, action: Action) -> None:
        await self.execute(str(getattr(action.payload, "command", "") or ""))

    async def execute(self, command: str) -> None:
        """
        Perform one movement command.

        Unknown names stop the base rather than being ignored. They should be
        impossible — the server validates against its registry before sending
        — so one arriving means the two sides disagree about the vocabulary,
        and a robot moving on an instruction nobody understood is the worse
        of the two failures.
        """
        async with self._lock:
            if command == STOP:
                self._current = STOP
                self._drive(0.0, 0.0)
                log.info("Base: stop")
                return

            speeds = self._speeds_for(command)
            if speeds is None:
                log.warning("Unknown movement %r — stopping the base.", command)
                self._current = STOP
                self._drive(0.0, 0.0)
                return

            if self._blocked and command in FORWARD_COMMANDS:
                # Latch it anyway: the way ahead clearing is what resumes it,
                # and that only works if we remember what was asked for.
                self._current = command
                log.info("Base: %s held — something is in the way", command)
                self._drive(0.0, 0.0)
                return

            self._current = command
            log.info("Base: %s", command)
            self._drive(*speeds)

    async def stop(self) -> None:
        """Stop and forget the movement. Used by shutdown and the hard stops."""
        async with self._lock:
            self._current = STOP
            self._drive(0.0, 0.0)

    async def set_blocked(self, blocked: bool) -> None:
        """
        Report whether the way ahead is obstructed.

        Called by the obstacle reflex. Blocking halts a forward movement
        without cancelling it, so clearing the obstacle resumes what was
        originally asked for rather than leaving the robot waiting for a
        command that already came.
        """
        async with self._lock:
            if blocked == self._blocked:
                return
            self._blocked = blocked

            if blocked:
                if self._current in FORWARD_COMMANDS:
                    log.warning("Obstacle ahead — holding %s", self._current)
                    self._drive(0.0, 0.0)
                return

            if self._current in FORWARD_COMMANDS:
                log.info("Way ahead is clear — resuming %s", self._current)
                speeds = self._speeds_for(self._current)
                if speeds is not None:
                    self._drive(*speeds)

    def _speeds_for(self, command: str):
        """One movement name to a (left, right) pair, or None if unknown."""
        drive = self._config.drive_speed
        turn = self._config.turn_speed
        return {
            "forward": (drive, drive),
            # No direction to home in on yet — no microphone array, no vision
            # tracking — so coming to you is driving forwards until told
            # otherwise. See the mapping proposal for what would change it.
            "come_here": (drive, drive),
            "backward": (-drive, -drive),
            # Opposite wheels pivot the round chassis on the spot rather than
            # sweeping an arc, which is the turn that fits an apartment.
            "turn_left": (-turn, turn),
            "turn_right": (turn, -turn),
        }.get(command)

    def _drive(self, left: float, right: float) -> None:
        try:
            if left == 0.0 and right == 0.0:
                self._driver.stop()
            else:
                self._driver.drive(left, right)
        except Exception as exc:
            # A GPIO failure mid-drive must not propagate into the dispatcher
            # and leave the wheels spinning on the last good command.
            log.error("Base driver failed on (%.2f, %.2f): %s", left, right, exc)
            try:
                self._driver.stop()
            except Exception:
                log.error("Base driver could not be stopped either.")
