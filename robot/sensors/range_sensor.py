"""
sensors/range_sensor.py — Forward distance, from a US-100 over UART.

The US-100 in UART mode is a request/response device: write one byte, read the
answer. 0x55 asks for distance and returns two bytes of millimetres, high byte
first. The port is opened with a short timeout so a sensor that is absent,
miswired, or in the wrong mode fails as a timeout instead of hanging the robot.

Serial I/O blocks, so the poll runs on a worker thread and publishes onto the
bus from there. Readings go out as `sensor.range` and nothing here decides
anything about them — the obstacle reflex does that, and a future map will read
the same topic.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config import RangeSensorConfig
from core.event_bus import Event, EventBus
from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger(__name__)

_DISTANCE_REQUEST = b"\x55"


class RangeSensor(BaseSensor):
    """Publishes forward distance in millimetres onto `sensor.range`."""

    name = "range_sensor"

    def __init__(self, event_bus: EventBus, config: RangeSensorConfig) -> None:
        super().__init__(event_bus)
        self.config = config
        self._serial = None
        self._task: Optional[asyncio.Task] = None

    @property
    def available(self) -> bool:
        """Whether the port actually opened. Reported in the capability manifest."""
        return self._serial is not None

    async def start(self) -> None:
        if not self.config.enabled:
            log.info("Range sensor disabled in config.")
            return

        try:
            import serial

            self._serial = serial.Serial(
                self.config.port,
                self.config.baud_rate,
                timeout=0.1,
            )
        except Exception as exc:
            # Optional hardware: say so clearly and carry on. The obstacle
            # reflex simply never fires, which is the documented behaviour of
            # a robot without a range sensor.
            log.warning("No range sensor on %s (%s) — obstacle stopping is off.", self.config.port, exc)
            self._serial = None
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        log.info("RangeSensor started on %s.", self.config.port)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        log.info("RangeSensor stopped.")

    async def _poll_loop(self) -> None:
        while self._running:
            distance = await asyncio.to_thread(self._read_distance_mm)
            if distance is not None:
                await self.event_bus.publish(
                    Event(topic="sensor.range", data=distance, source=self.name)
                )
            await asyncio.sleep(self.config.poll_interval_seconds)

    def _read_distance_mm(self) -> Optional[int]:
        """One reading, or None if it was absent or implausible."""
        if self._serial is None:
            return None
        try:
            self._serial.reset_input_buffer()
            self._serial.write(_DISTANCE_REQUEST)
            raw = self._serial.read(2)
        except Exception as exc:
            log.warning("Range sensor read failed: %s", exc)
            return None

        if len(raw) != 2:
            return None

        distance = (raw[0] << 8) | raw[1]
        if distance <= 0 or distance > self.config.max_valid_mm:
            # Out of range reads as a nonsense number rather than an error.
            # Discarding it is right: "nothing within 4.5 m" and "the sensor
            # is confused" look identical here, and neither is an obstacle.
            return None
        return distance
