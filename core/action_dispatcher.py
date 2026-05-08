"""
core/action_dispatcher.py — Validates and dispatches structured actions.

The DecisionEngine produces a list of Action objects.
The ActionDispatcher routes each action to its registered handler.

New action types are added by:
  1. Defining a dataclass in actions/action_types.py
  2. Writing a handler subclassing BaseActionHandler
  3. Registering the handler here via dispatcher.register_handler(handler)
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

from actions.action_types import Action, parse_action
from actions.base_action_handler import BaseActionHandler
from utils.logger import get_logger

log = get_logger(__name__)


class ActionDispatcher:
    """
    Routes structured actions to their registered handlers.

    Handlers are keyed by the action type string they handle.
    Unknown action types are logged as warnings and skipped.

    Usage:
        dispatcher = ActionDispatcher()
        dispatcher.register_handler(SpeakHandler(tts_engine))
        dispatcher.register_handler(EyeExpressionHandler(eye_controller))

        await dispatcher.dispatch_all(actions)
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, BaseActionHandler] = {}

    def register_handler(self, handler: BaseActionHandler) -> None:
        """
        Register a handler for a specific action type.

        Args:
            handler: Instance of a BaseActionHandler subclass.
                     Its action_type property determines which actions it handles.

        Raises:
            ValueError: If a handler for this action type is already registered.
        """
        action_type = handler.action_type
        if action_type in self._handlers:
            raise ValueError(
                f"Handler for action type '{action_type}' is already registered."
            )
        self._handlers[action_type] = handler
        log.debug("Registered handler for action type: %s", action_type)

    async def dispatch(self, action: Action) -> None:
        """
        Dispatch a single action to its handler.

        If no handler is registered, the action is logged and skipped.
        Handler exceptions are caught and logged; they do not propagate.

        Args:
            action: A typed Action instance.
        """
        handler = self._handlers.get(action.type)
        if handler is None:
            log.warning("No handler registered for action type '%s' — skipping.", action.type)
            return

        try:
            log.debug("Dispatching action: type=%s", action.type)
            await handler.handle(action)
        except Exception as exc:
            log.error("Handler for '%s' raised an exception: %s", action.type, exc)

    async def dispatch_all(self, actions: List[Action]) -> None:
        """
        Dispatch a list of actions sequentially.

        Actions are executed in the order returned by the decision LLM.
        Use sequential execution to preserve intent ordering
        (e.g. speak before changing expression).

        TODO: Consider parallel dispatch for independent actions if needed.

        Args:
            actions: List of Action instances to execute.
        """
        log.info("Dispatching %d action(s).", len(actions))
        for action in actions:
            await self.dispatch(action)

    async def dispatch_raw(self, raw_actions: List[dict]) -> None:
        """
        Parse raw action dicts from the LLM response and dispatch them.

        This is the main entry point called by DecisionEngine after
        it receives the structured LLM output.

        Args:
            raw_actions: List of raw dicts, each with at least a "type" key.
        """
        actions: List[Action] = []
        for raw in raw_actions:
            try:
                action = parse_action(raw)
                actions.append(action)
            except Exception as exc:
                log.error("Failed to parse action %r: %s", raw, exc)

        await self.dispatch_all(actions)
