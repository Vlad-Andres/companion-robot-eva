"""
behaviors/idle_blink.py — Autonomous idle blink behaviour.

Runs as a background service that makes the robot blink periodically,
even when no speech or decision cycle is happening.

Blink interval is randomised within a configurable min/max range to feel
natural rather than mechanical.

The blink is dispatched through the normal EventBus → ActionDispatcher
pipeline so it gets logged and tracked in ContextManager like any other action.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from core.event_bus import Event, EventBus
from utils.logger import get_logger

log = get_logger(__name__)


class IdleBlinkService:
    """
    Periodically triggers a random blink animation on the eye display.

    Publishes a "decision.actions" event with a BLINK_SHORT or BLINK_LONG
    animation, which the ActionDispatcher routes to EyeAnimationHandler.

    This runs independently of the decision LLM — it's pure reflex behaviour.

    Configuration:
        min_interval: Minimum seconds between blinks.
        max_interval: Maximum seconds between blinks.
        long_blink_chance: Probability (0–1) of a slow blink vs a quick one.
    """

    name = "idle_blink"

    def __init__(
        self,
        event_bus: EventBus,
        min_interval: float = 3.0,
        max_interval: float = 8.0,
        long_blink_chance: float = 0.2,
    ) -> None:
        """
        Args:
            event_bus:         Shared EventBus to publish blink actions onto.
            min_interval:      Minimum seconds between blinks.
            max_interval:      Maximum seconds between blinks.
            long_blink_chance: Probability that a blink will be slow (BLINK_LONG).
        """
        self.event_bus = event_bus
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.long_blink_chance = long_blink_chance
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background blink loop."""
        self._running = True
        self._task = asyncio.create_task(self._blink_loop(), name="idle_blink")
        log.info(
            "IdleBlinkService started (interval %.1f–%.1fs).",
            self.min_interval,
            self.max_interval,
        )

    async def stop(self) -> None:
        """Stop the blink loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("IdleBlinkService stopped.")

    async def _blink_loop(self) -> None:
        """
        Main loop: wait a random interval, then publish a blink action.

        The first blink is delayed by a full interval so the robot doesn't
        blink immediately on startup.
        """
        while self._running:
            delay = random.uniform(self.min_interval, self.max_interval)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break

            animation = (
                "BLINK_LONG"
                if random.random() < self.long_blink_chance
                else "BLINK_SHORT"
            )

            log.debug("Idle blink: %s", animation)
            await self.event_bus.publish(
                Event(
                    topic="decision.actions",
                    data=[
                        {
                            "type": "play_eye_animation",
                            "payload": {"animation": animation},
                        }
                    ],
                    source=self.name,
                )
            )
