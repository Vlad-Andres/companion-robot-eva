"""
telemetry.py — Seeing what the pipeline is actually doing.

The server already knows everything worth knowing: the level of every frame,
what the voice detector scored it, exactly which audio it decided to keep, and
how long each stage took. None of that was visible, which makes "why did it
feel slow?" impossible to answer from the outside.

This publishes it to a live dashboard at GET /debug.

Two rules keep it honest:

  * Disabled by default, and when disabled it is NullTelemetry — every call is
    an empty method, so there is nothing to switch off in the hot path.
  * emit() never awaits and never blocks. Events go into a small per-client
    queue and are dropped when it is full; a slow browser tab must never be
    able to stall the audio loop.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Protocol

from log import logger

_log = logger("eva.telemetry")

# Enough to absorb a slow render without letting a stuck tab grow forever.
_CLIENT_QUEUE_SIZE = 256


class Telemetry(Protocol):
    """Reports what the pipeline is doing. Implementations must never block."""

    @property
    def enabled(self) -> bool: ...

    def emit(self, event_type: str, **fields: Any) -> None: ...

    def frame(self, *, rms: float, speech_probability: float, in_speech: bool) -> None: ...

    def timed(self, stage: str) -> Any: ...


class NullTelemetry:
    """The default. Every method is a no-op so nothing is measured or sent."""

    @property
    def enabled(self) -> bool:
        return False

    def emit(self, event_type: str, **fields: Any) -> None:
        return

    def frame(self, *, rms: float, speech_probability: float, in_speech: bool) -> None:
        return

    @contextmanager
    def timed(self, stage: str) -> Iterator[None]:
        yield


class DebugTelemetry:
    """Fans events out to every connected dashboard."""

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._started_at = time.monotonic()

    @property
    def enabled(self) -> bool:
        return True

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ------------------------------------------------------------------
    # Producing
    # ------------------------------------------------------------------

    def emit(self, event_type: str, **fields: Any) -> None:
        """Queue one event for every dashboard. Never blocks, never raises."""
        if not self._clients:
            return

        event = {"type": event_type, "t": round(time.monotonic() - self._started_at, 3), **fields}
        for queue in self._clients:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # This tab is behind; skip rather than slow the pipeline.

    def frame(self, *, rms: float, speech_probability: float, in_speech: bool) -> None:
        """One audio frame. Called ~31 times a second, so the payload is small."""
        self.emit(
            "frame",
            rms=round(rms, 4),
            p=round(speech_probability, 3),
            speech=in_speech,
        )

    @contextmanager
    def timed(self, stage: str) -> Iterator[None]:
        """Time a pipeline stage and report how long it took."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.emit("stage", stage=stage, ms=round((time.perf_counter() - started) * 1000, 1))

    # ------------------------------------------------------------------
    # Consuming
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_CLIENT_QUEUE_SIZE)
        self._clients.add(queue)
        _log.info("Debug dashboard connected (%d watching)", len(self._clients))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)
        _log.info("Debug dashboard disconnected (%d watching)", len(self._clients))


def build_telemetry(*, enabled: bool) -> Telemetry:
    if not enabled:
        return NullTelemetry()
    _log.info("Debug telemetry on — dashboard at /debug")
    return DebugTelemetry()
