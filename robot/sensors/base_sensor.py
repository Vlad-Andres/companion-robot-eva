"""
sensors/base_sensor.py — Abstract base class for all robot sensors.

Sensors are producers: they capture raw data from hardware and publish
events onto the EventBus for downstream perception components.

Every sensor must implement:
  - name:   Unique identifier string.
  - start(): Begin background capture loop.
  - stop():  Halt capture and release hardware resources.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.event_bus import EventBus


class BaseSensor(ABC):
    """
    Abstract base for all robot sensor adapters.

    Attributes:
        name:      Unique sensor name string (e.g. "camera", "microphone").
        event_bus: Reference to the shared EventBus for publishing events.
    """

    name: str  # Subclasses must define this as a class attribute.

    def __init__(self, event_bus: EventBus) -> None:
        """
        Args:
            event_bus: Shared EventBus instance.
        """
        self.event_bus = event_bus
        self._running: bool = False

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize hardware and start the background capture loop.

        Should create an asyncio background task (not block the caller).
        Set self._running = True before launching the loop.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the capture loop and release hardware resources.

        Should set self._running = False and cancel any background tasks.
        """
        ...
