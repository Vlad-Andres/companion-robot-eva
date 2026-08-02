"""
memory/memory_store.py — Short-term and long-term memory abstraction.

Memory allows the robot to:
  - Remember recent events (short-term ring buffer in RAM).
  - Persist important memories across restarts (long-term JSON file).
  - Retrieve relevant memories for ContextBuilder.

Future evolution:
  - Replace the JSON file with a vector database (e.g. ChromaDB)
    for semantic similarity search.
  - Add episodic memory (full session logs).
  - Add semantic summarization of old memories.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class MemoryEvent:
    """
    A single stored memory event.

    Attributes:
        timestamp:  Unix timestamp when this memory was recorded.
        event_type: Category string (e.g. "speech", "object_seen", "action").
        content:    The memory content (string, dict, or any JSON-serialisable value).
        importance: Salience score 0.0–1.0 (higher = more important to retain).
    """
    timestamp: float
    event_type: str
    content: Any
    importance: float = 0.5


class MemoryStore:
    """
    Hybrid short-term and long-term memory for the robot.

    Short-term memory:
        A fixed-capacity deque of recent MemoryEvents stored in RAM.
        Oldest events are automatically dropped when capacity is exceeded.
        Used by ContextBuilder to inject recent context into the LLM.

    Long-term memory:
        Persistent JSON file storage for important memories.
        Loaded at startup, saved when add_event() is called with importance > threshold.
        TODO: Replace with a proper database for larger memory sets.

    Usage:
        store = MemoryStore(config)
        store.load()

        store.add_event(MemoryEvent(
            timestamp=time.time(),
            event_type="speech",
            content="User said hello",
            importance=0.7,
        ))

        recent = store.get_recent(n=5)
        all_long = store.get_long_term()
    """

    LONG_TERM_IMPORTANCE_THRESHOLD = 0.7

    def __init__(self, capacity: int = 50, long_term_path: str = "memory.json") -> None:
        """
        Args:
            capacity:        Max events in the short-term ring buffer.
            long_term_path:  File path for persistent long-term storage.
        """
        self._capacity = capacity
        self._long_term_path = long_term_path
        self._short_term: Deque[MemoryEvent] = deque(maxlen=capacity)
        self._long_term: List[MemoryEvent] = []

    def load(self) -> None:
        """
        Load long-term memory from the JSON file (if it exists).

        Should be called once at startup before any add_event() calls.
        """
        if not os.path.exists(self._long_term_path):
            log.info("No long-term memory file found at '%s' — starting fresh.", self._long_term_path)
            return

        try:
            with open(self._long_term_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._long_term = [MemoryEvent(**item) for item in raw]
            log.info("Loaded %d long-term memories from '%s'.", len(self._long_term), self._long_term_path)
        except Exception as exc:
            log.error("Failed to load long-term memory: %s", exc)

    def save(self) -> None:
        """
        Persist long-term memory to the JSON file.

        TODO: Add async save with write-ahead strategy to avoid blocking.
        """
        try:
            with open(self._long_term_path, "w", encoding="utf-8") as f:
                json.dump([asdict(m) for m in self._long_term], f, indent=2)
            log.debug("Saved %d long-term memories.", len(self._long_term))
        except Exception as exc:
            log.error("Failed to save long-term memory: %s", exc)

    def add_event(self, event: MemoryEvent) -> None:
        """
        Add a new memory event.

        Always adds to short-term memory.
        If importance >= LONG_TERM_IMPORTANCE_THRESHOLD, also persists to long-term.

        Args:
            event: The MemoryEvent to store.
        """
        self._short_term.append(event)
        log.debug("Added short-term memory: type=%s importance=%.2f", event.event_type, event.importance)

        if event.importance >= self.LONG_TERM_IMPORTANCE_THRESHOLD:
            self._long_term.append(event)
            self.save()
            log.debug("Promoted to long-term memory: type=%s", event.event_type)

    def get_recent(self, n: int = 10) -> List[MemoryEvent]:
        """
        Return the n most recent short-term memory events.

        Args:
            n: Number of recent events to return.

        Returns:
            List of MemoryEvent, most recent last.
        """
        items = list(self._short_term)
        return items[-n:]

    def get_long_term(self) -> List[MemoryEvent]:
        """
        Return all long-term memory events.

        Returns:
            Ordered list of MemoryEvent (oldest first).
        """
        return list(self._long_term)

    def search(self, query: str) -> List[MemoryEvent]:
        """
        Search memories by keyword match (naive string search).

        TODO: Replace with vector similarity search for semantic retrieval.

        Args:
            query: Search string to match against memory content.

        Returns:
            List of matching MemoryEvents from combined short + long-term store.
        """
        # TODO: Implement semantic search via embedding model.
        query_lower = query.lower()
        results = []
        all_memories = list(self._short_term) + self._long_term
        for memory in all_memories:
            content_str = str(memory.content).lower()
            if query_lower in content_str:
                results.append(memory)
        return results
