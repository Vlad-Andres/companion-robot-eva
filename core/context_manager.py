"""
core/context_manager.py — Robot internal state and conversation context.

The ContextManager is the single source of truth for what the robot
currently knows about:
  - its environment (perceived objects, last image)
  - recent human speech
  - conversation history
  - its own emotional/expressive state
  - recent actions taken

All components read from and write to this shared context.
The DecisionEngine reads a snapshot to build the LLM payload.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class DetectedObject:
    """
    A single object detected by the vision API.

    Attributes:
        label:      Human-readable object name (e.g. "person", "cup").
        x:          Bounding box left edge in pixels.
        y:          Bounding box top edge in pixels.
        width:      Bounding box width in pixels.
        height:     Bounding box height in pixels.
        confidence: Model confidence score, 0.0 – 1.0.
    """
    label: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0


@dataclass
class ConversationTurn:
    """
    A single turn in the conversation history.

    Attributes:
        role:    "human" or "robot".
        content: The spoken or decided text.
    """
    role: str   # "human" | "robot"
    content: str


class ContextManager:
    """
    Shared robot context and state store.

    Thread-safe reads/writes via an internal lock (for any sync callers).
    Async callers should use async-safe patterns; for now a simple lock is used.

    Attributes managed:
        current_objects:     Most recent list of detected visual objects.
        last_speech:         Most recent transcribed human speech.
        conversation_history: Rolling list of ConversationTurns.
        current_expression:  Current robot eye expression name.
        recent_actions:      Recently dispatched action type names.
        custom_state:        Arbitrary key-value store for extensions.
    """

    def __init__(self, max_history_turns: int = 10) -> None:
        self._lock = threading.Lock()
        self._max_history = max_history_turns

        self.current_objects: List[DetectedObject] = []
        self.last_speech: Optional[str] = None
        self.conversation_history: List[ConversationTurn] = []
        self.current_expression: str = "neutral"
        self.recent_actions: List[str] = []
        self.custom_state: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Vision context
    # ------------------------------------------------------------------

    def update_objects(self, objects: List[DetectedObject]) -> None:
        """
        Replace the current detected objects list.

        Called by VisionClient after a successful API response.

        Args:
            objects: New list of DetectedObject instances.
        """
        with self._lock:
            self.current_objects = objects
        log.debug("Context updated: %d object(s) detected", len(objects))

    def get_objects(self) -> List[DetectedObject]:
        """Return a copy of the current detected objects list."""
        with self._lock:
            return list(self.current_objects)

    # ------------------------------------------------------------------
    # Speech / conversation context
    # ------------------------------------------------------------------

    def update_speech(self, text: str) -> None:
        """
        Record new transcribed speech from the human.

        Also appends a ConversationTurn with role="human".

        Args:
            text: Transcribed speech string.
        """
        with self._lock:
            self.last_speech = text
            self._append_history(ConversationTurn(role="human", content=text))
        log.debug("Context updated: speech = %r", text)

    def record_robot_speech(self, text: str) -> None:
        """
        Record what the robot said (called by SpeakHandler).

        Appends a ConversationTurn with role="robot".

        Args:
            text: Text the robot spoke.
        """
        with self._lock:
            self._append_history(ConversationTurn(role="robot", content=text))

    def get_conversation_history(self) -> List[ConversationTurn]:
        """Return a copy of the conversation history."""
        with self._lock:
            return list(self.conversation_history)

    def _append_history(self, turn: ConversationTurn) -> None:
        """Internal: append and trim history. Must be called under lock."""
        self.conversation_history.append(turn)
        if len(self.conversation_history) > self._max_history:
            self.conversation_history = self.conversation_history[-self._max_history:]

    # ------------------------------------------------------------------
    # Expression / action state
    # ------------------------------------------------------------------

    def update_expression(self, expression: str) -> None:
        """
        Record the robot's current eye expression.

        Called by EyeExpressionHandler after executing an eye action.

        Args:
            expression: Expression name string (e.g. "happy", "neutral").
        """
        with self._lock:
            self.current_expression = expression
        log.debug("Context updated: expression = %s", expression)

    def record_action(self, action_type: str) -> None:
        """
        Append an action type to recent_actions (capped at 20).

        Args:
            action_type: The action type string (e.g. "speak").
        """
        with self._lock:
            self.recent_actions.append(action_type)
            if len(self.recent_actions) > 20:
                self.recent_actions = self.recent_actions[-20:]

    # ------------------------------------------------------------------
    # Custom / extension state
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """
        Store an arbitrary value in custom_state.

        Use this for extension modules that need persistent state
        without modifying ContextManager directly.

        Args:
            key:   Unique state key.
            value: Any serialisable value.
        """
        with self._lock:
            self.custom_state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from custom_state.

        Args:
            key:     State key.
            default: Value to return if key is absent.
        """
        with self._lock:
            return self.custom_state.get(key, default)

    # ------------------------------------------------------------------
    # Snapshot (for DecisionEngine / ContextBuilder)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """
        Return an immutable-ish dict snapshot of the current context.

        Used by ContextBuilder to assemble the LLM payload.

        Returns:
            Dict with keys: objects, last_speech, history,
            expression, recent_actions, custom.
        """
        with self._lock:
            return {
                "objects": [vars(o) for o in self.current_objects],
                "last_speech": self.last_speech,
                "history": [vars(t) for t in self.conversation_history],
                "expression": self.current_expression,
                "recent_actions": list(self.recent_actions),
                "custom": dict(self.custom_state),
            }
