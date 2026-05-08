"""
perception/base_perception.py — Abstract base for perception API clients.

Perception clients subscribe to sensor events, forward data to an AI API,
parse the structured response, update ContextManager, and re-publish
the result on the EventBus.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.context_manager import ContextManager
from core.event_bus import Event, EventBus


class BasePerceptionClient(ABC):
    """
    Abstract base for AI perception API clients.

    Subclasses:
        VisionClient  — subscribes to "sensor.vision" events.
        SpeechClient  — subscribes to "sensor.audio" events.

    Lifecycle:
        start() → subscribes to sensor topic, may start background tasks.
        stop()  → unsubscribes, cancels tasks, releases resources.
    """

    name: str  # Unique service name, e.g. "vision_client".

    def __init__(
        self,
        event_bus: EventBus,
        context_manager: ContextManager,
    ) -> None:
        """
        Args:
            event_bus:       Shared EventBus for subscribe/publish.
            context_manager: Shared ContextManager for state updates.
        """
        self.event_bus = event_bus
        self.context = context_manager

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
        Handle a sensor event: call the API, parse the result,
        update context, and publish a perception event.

        Args:
            event: A sensor Event from the EventBus.
        """
        ...
