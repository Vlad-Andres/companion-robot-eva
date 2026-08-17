"""
behaviors/motion_safety.py — Stopping the wheels without asking the server.

Movement is latched: `forward` runs until something stops it. That is what was
asked for, and with a working link and a range sensor it is safe — a spoken
"stop" arrives in under a second and the obstacle reflex handles walls. This
covers the two cases where neither of those is true.

**The link drops.** Not a timeout: a commanded movement is never cut short
while the server is there, because "forward" should mean forward. But a robot
whose server has vanished cannot be told to stop, so it stops itself.

**The button.** While Eva is speaking her microphone is muted so she does not
transcribe herself, and for those few seconds a spoken "stop" has nowhere to
land. The WM8960 HAT already carries a button; this makes it mean stop. It is
the only stop that works when everything else has failed, which is a reasonable
thing to have on something with wheels.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from actions.move_base_handler import MoveBaseHandler
from config import EmergencyStopConfig
from core.event_bus import Event, EventBus
from utils.logger import get_logger

log = get_logger(__name__)


class MotionSafetyService:
    """Hard stops: a lost server, and a physical button."""

    name = "motion_safety"

    def __init__(
        self,
        event_bus: EventBus,
        move_base: MoveBaseHandler,
        config: EmergencyStopConfig,
    ) -> None:
        self.event_bus = event_bus
        self._move_base = move_base
        self._config = config
        self._button = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.event_bus.subscribe("perception.backend_disconnected", self._on_disconnected)
        self._attach_button()
        log.info("MotionSafetyService started.")

    async def stop(self) -> None:
        self.event_bus.unsubscribe("perception.backend_disconnected", self._on_disconnected)
        if self._button is not None:
            try:
                self._button.close()
            except Exception:
                pass
            self._button = None
        log.info("MotionSafetyService stopped.")

    # ------------------------------------------------------------------

    async def _on_disconnected(self, _event: Event) -> None:
        if not self._move_base.is_moving:
            return
        log.warning("Lost the server while moving — stopping the base.")
        await self._move_base.stop()

    def _attach_button(self) -> None:
        if not self._config.enabled:
            return
        try:
            from gpiozero import Button

            self._button = Button(self._config.button_pin, pull_up=True, bounce_time=0.05)
            self._button.when_pressed = self._on_button
            log.info("Emergency stop on GPIO %d.", self._config.button_pin)
        except Exception as exc:
            log.warning("No emergency stop button (%s) — voice and obstacle stops only.", exc)
            self._button = None

    def _on_button(self) -> None:
        """
        Called from gpiozero's own thread, not the event loop.

        Hopping threads is why this is not simply `await stop()`: touching the
        loop from the callback thread directly is how a stop gets silently
        dropped, and a dropped stop is the one this exists to prevent.
        """
        log.warning("Emergency stop pressed.")
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._move_base.stop(), self._loop)
