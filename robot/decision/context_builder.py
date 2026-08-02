"""
decision/context_builder.py — Assembles the context payload for the decision LLM.

Reads a snapshot from ContextManager and shapes it into the JSON structure
that the decision LLM API expects.

The payload format can be evolved here without touching other components.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.context_manager import ContextManager
from utils.logger import get_logger

log = get_logger(__name__)


class ContextBuilder:
    """
    Constructs the context payload sent to the decision LLM.

    The context payload gives the LLM everything it needs to decide
    what actions the robot should take:
      - perceived environment (objects, scene)
      - recent human speech
      - conversation history
      - robot's current state (expression, recent actions)
      - memory highlights (TODO: integrate MemoryStore)

    Usage:
        builder = ContextBuilder(context_manager)
        payload = builder.build()
        # payload is a dict, JSON-serialisable
    """

    def __init__(self, context_manager: ContextManager) -> None:
        """
        Args:
            context_manager: The shared ContextManager instance.
        """
        self._context = context_manager

    def build(self) -> Dict[str, Any]:
        """
        Build and return the context payload dict.

        Returns:
            A JSON-serialisable dict ready to send to the decision LLM API.

        Structure:
            {
                "perception": {
                    "objects": [...],         # Current detected objects
                    "last_speech": "...",     # Most recent transcribed speech
                },
                "state": {
                    "expression": "...",      # Current eye expression
                    "recent_actions": [...],  # Last N action types taken
                },
                "conversation": [
                    {"role": "human", "content": "..."},
                    {"role": "robot", "content": "..."},
                    ...
                ],
                "memory": [],                 # TODO: short/long-term memories
                "instructions": "...",        # System prompt for the LLM (TODO)
            }
        """
        snapshot = self._context.snapshot()

        payload = {
            "perception": {
                "objects": snapshot["objects"],
                "last_speech": snapshot["last_speech"],
            },
            "state": {
                "expression": snapshot["expression"],
                "recent_actions": snapshot["recent_actions"],
            },
            "conversation": snapshot["history"],
            "memory": self._get_memory_context(),
            "instructions": self._get_system_instructions(),
        }

        log.debug(
            "Built context payload: %d object(s), speech=%r, history=%d turn(s)",
            len(snapshot["objects"]),
            snapshot["last_speech"],
            len(snapshot["history"]),
        )
        return payload

    def _get_memory_context(self) -> List[Dict[str, Any]]:
        """
        Retrieve relevant memories to include in the context payload.

        TODO: Query MemoryStore for recent or relevant memories.
              This may involve semantic search in future (vector DB).

        Returns:
            List of memory dicts to include in the payload.
        """
        # TODO: Implement memory retrieval.
        return []

    def _get_system_instructions(self) -> str:
        """
        Return the system prompt that shapes the LLM's behaviour and output format.

        This prompt should:
          - Describe the robot's persona.
          - Specify the required structured output format.
          - List available action types and their payloads.
          - Instruct the LLM to ONLY return valid JSON actions.

        TODO: Load from a configurable prompt file or config field.

        Returns:
            System instruction string.
        """
        # TODO: Replace with a real, well-crafted system prompt.
        return (
            "You are a companion robot. "
            "Respond only with a JSON object containing an 'actions' list. "
            "Available action types: speak, set_eye_expression, play_eye_animation. "
            "Example: {\"actions\": [{\"type\": \"speak\", \"payload\": {\"text\": \"Hello!\"}}]}"
        )
