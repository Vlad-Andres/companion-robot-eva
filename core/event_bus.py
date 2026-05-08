"""
core/event_bus.py — Async publish/subscribe event bus.

All inter-component communication flows through this bus.
Producers publish events; consumers subscribe to topics.

Well-known topics:
    sensor.vision       — raw camera frame (bytes or numpy array)
    sensor.audio        — raw audio chunk (bytes)
    perception.objects  — list of DetectedObject from vision API
    perception.speech   — transcribed text string from STT API
    decision.actions    — list of Action objects from decision LLM
    action.complete     — notification that an action finished executing

Components subscribe by calling event_bus.subscribe(topic, callback).
The callback is an async function: async def handler(event: Event) -> None.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List

from utils.logger import get_logger

log = get_logger(__name__)

# Type alias for async event handlers
AsyncHandler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """
    A single event on the bus.

    Attributes:
        topic:   Dotted topic string, e.g. "sensor.vision".
        data:    The event payload. Type depends on the topic.
        source:  Optional name of the component that produced this event.
    """
    topic: str
    data: Any
    source: str = "unknown"


class EventBus:
    """
    Async publish/subscribe event bus.

    Handlers are called concurrently when an event is published.
    Exceptions in handlers are logged but do not interrupt other handlers.

    Usage:
        bus = EventBus()

        # Subscribe
        async def on_vision(event: Event):
            frame = event.data
            ...

        bus.subscribe("sensor.vision", on_vision)

        # Publish
        await bus.publish(Event(topic="sensor.vision", data=frame, source="camera"))
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[AsyncHandler]] = {}

    def subscribe(self, topic: str, handler: AsyncHandler) -> None:
        """
        Register an async callback for the given topic.

        Args:
            topic:   Topic string to listen on.
            handler: Async callable(Event) -> None.
        """
        self._handlers.setdefault(topic, []).append(handler)
        log.debug("Subscribed %s to topic '%s'", handler, topic)

    def unsubscribe(self, topic: str, handler: AsyncHandler) -> None:
        """
        Remove a previously registered handler.

        Args:
            topic:   Topic string.
            handler: The exact handler object that was subscribed.
        """
        handlers = self._handlers.get(topic, [])
        if handler in handlers:
            handlers.remove(handler)
            log.debug("Unsubscribed %s from topic '%s'", handler, topic)

    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers of its topic.

        All handlers are awaited concurrently via asyncio.gather.
        Handler exceptions are caught and logged; they do not propagate.

        Args:
            event: The event to broadcast.
        """
        handlers = self._handlers.get(event.topic, [])
        if not handlers:
            log.debug("No subscribers for topic '%s'", event.topic)
            return

        log.debug("Publishing event on '%s' from '%s'", event.topic, event.source)

        # TODO: Consider adding a max-concurrency semaphore if handlers are slow.
        results = await asyncio.gather(
            *[handler(event) for handler in handlers],
            return_exceptions=True,
        )

        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                log.error(
                    "Handler %s raised exception on topic '%s': %s",
                    handler,
                    event.topic,
                    result,
                )
