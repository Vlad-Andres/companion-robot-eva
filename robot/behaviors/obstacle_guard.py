"""
behaviors/obstacle_guard.py — Do not drive into things.

A local reflex, and deliberately so. This is the one piece of the movement
path that must keep working when the network does not: the server decides
where to go, this decides whether the next few centimetres are safe, and it
answers in the time it takes a serial read to come back rather than a round
trip to the Mac.

Two thresholds, not one. Blocking at 25 cm and clearing at 35 cm means a
sensor reading 250 mm one moment and 251 mm the next cannot start and stop the
motors several times a second. The gap is the hysteresis.

It stops *forward* movement only. Reversing and turning stay available, or the
first wall Eva met would be the last place she ever went.
"""

from __future__ import annotations

from actions.move_base_handler import MoveBaseHandler
from config import RangeSensorConfig
from core.event_bus import Event, EventBus
from utils.logger import get_logger

log = get_logger(__name__)


class ObstacleGuard:
    """Holds forward movement while something is close in front."""

    name = "obstacle_guard"

    def __init__(
        self,
        event_bus: EventBus,
        move_base: MoveBaseHandler,
        config: RangeSensorConfig,
    ) -> None:
        self.event_bus = event_bus
        self._move_base = move_base
        self._config = config
        self._blocked = False

    async def start(self) -> None:
        self.event_bus.subscribe("sensor.range", self._on_range)
        log.info(
            "ObstacleGuard started — holding forward under %d mm, clearing at %d mm.",
            self._config.stop_distance_mm,
            self._config.clear_distance_mm,
        )

    async def stop(self) -> None:
        self.event_bus.unsubscribe("sensor.range", self._on_range)
        log.info("ObstacleGuard stopped.")

    async def _on_range(self, event: Event) -> None:
        distance = event.data
        if not isinstance(distance, (int, float)):
            return

        blocked = self._next_state(float(distance))
        if blocked == self._blocked:
            return

        self._blocked = blocked
        if blocked:
            log.warning("Obstacle at %d mm.", int(distance))
        await self._move_base.set_blocked(blocked)

    def _next_state(self, distance: float) -> bool:
        """
        Whether the way ahead counts as blocked, given where it already stood.

        Which threshold applies depends on the current state — that is the
        whole point of having two.
        """
        if self._blocked:
            return distance < self._config.clear_distance_mm
        return distance < self._config.stop_distance_mm
