"""
perception/base_perception.py — Abstract base for perception clients.

Perception clients subscribe to sensor events, forward data to the server,
parse the response, and re-publish the result on the EventBus.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.event_bus import Event, EventBus


class BasePerceptionClient(ABC):
    """
    Abstract base for perception clients.

    Subclasses:
        SpeechClient — subscribes to "sensor.audio" events.

    Lifecycle:
        start() → subscribes to sensor topic, may start background tasks.
        stop()  → unsubscribes, cancels tasks, releases resources.
    """

    name: str  # Unique service name, e.g. "speech_client".

    def __init__(self, event_bus: EventBus) -> None:
        """
        Args:
            event_bus: Shared EventBus for subscribe/publish.
        """
        self.event_bus = event_bus

    @abstractmethod
    async def start(self) -> None:
        """Subscribe to relevant sensor event topic and begin processing."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Unsubscribe and clean up."""
        ...

    @abstractmethod
    async def process(self, event: Event) -> None:
        """
        Handle a sensor event: forward it to the server and publish the
        resulting perception event.

        Args:
            event: A sensor Event from the EventBus.
        """
        ...
