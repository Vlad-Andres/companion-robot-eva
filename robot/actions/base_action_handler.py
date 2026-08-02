"""
actions/base_action_handler.py — Abstract base class for action handlers.

Every action type has exactly one handler that knows how to execute it.
Handlers are registered with the ActionDispatcher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from actions.action_types import Action


class BaseActionHandler(ABC):
    """
    Abstract base class for all robot action handlers.

    Subclass this to add support for a new action type.

    Attributes:
        action_type: The action type string this handler handles.
                     Must match an ActionType enum value string.

    Example:
        class MyHandler(BaseActionHandler):
            action_type = "my_action"

            async def handle(self, action: Action) -> None:
                payload = action.payload   # typed payload dataclass
                # do something with payload
    """

    action_type: str  # Subclasses must define this as a class attribute.

    @abstractmethod
    async def handle(self, action: Action) -> None:
        """
        Execute the given action.

        Args:
            action: A typed Action instance with action_type matching
                    this handler's action_type.

        This method should not raise unless there is an unrecoverable error.
        Log and continue on non-fatal failures.
        """
        ...
