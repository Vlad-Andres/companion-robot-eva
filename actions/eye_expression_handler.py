"""
actions/eye_expression_handler.py — Handler for eye animation actions.

Handles both:
  - "set_eye_expression": sets a persistent expression (happy, sleep, etc.)
  - "play_eye_animation": plays a one-shot animation sequence (wakeup, blink, etc.)

Delegates to the EyeController from display/eye_controller.py.
"""

from __future__ import annotations

from actions.action_types import (
    Action,
    ActionType,
    PlayEyeAnimationPayload,
    SetEyeExpressionPayload,
)
from actions.base_action_handler import BaseActionHandler
from utils.logger import get_logger

log = get_logger(__name__)


class EyeExpressionHandler(BaseActionHandler):
    """
    Handles "set_eye_expression" actions.

    Maps expression names from the LLM response to EyeController methods.

    Expression name conventions (case-insensitive):
        "happy"       → EyeController.happy()
        "sleep"       → EyeController.sleep()
        "neutral"     → EyeController.reset()
        "blink"       → EyeController.blink_short()
        ... (extend as needed)

    Dependencies:
        eye_controller: EyeController instance (from display/eye_controller.py).
        context_manager: ContextManager for recording expression state.
    """

    action_type = ActionType.SET_EYE_EXPRESSION

    def __init__(self, eye_controller=None, context_manager=None) -> None:
        """
        Args:
            eye_controller:  EyeController instance.
            context_manager: ContextManager for state updates.
        """
        self._eyes = eye_controller
        self._context = context_manager

    async def handle(self, action: Action) -> None:
        """
        Execute the set_eye_expression action.

        Args:
            action: Action with payload of type SetEyeExpressionPayload.
        """
        payload: SetEyeExpressionPayload = action.payload
        expression = payload.expression.lower()

        log.info("Setting eye expression: %s", expression)

        if self._eyes is not None:
            # TODO: Map expression strings to EyeController methods.
            #       Add more mappings as the expression vocabulary grows.
            expression_map = {
                "happy": self._eyes.happy,
                "sleep": self._eyes.sleep,
                "neutral": self._eyes.reset,
                "default": self._eyes.reset,
                "blink": self._eyes.blink_short,
                "blink_long": self._eyes.blink_long,
                "blink_short": self._eyes.blink_short,
                "saccade": self._eyes.saccade_random,
            }

            method = expression_map.get(expression)
            if method is None:
                log.warning("Unknown expression '%s' — falling back to neutral.", expression)
                method = self._eyes.reset

            # EyeController methods are synchronous; run in executor to avoid blocking.
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, method)
        else:
            log.warning("EyeController not available — skipping display for '%s'.", expression)

        # Always update context, even when display hardware is absent.
        if self._context:
            self._context.update_expression(expression)
            self._context.record_action(ActionType.SET_EYE_EXPRESSION)


class EyeAnimationHandler(BaseActionHandler):
    """
    Handles "play_eye_animation" actions.

    Plays a one-shot named animation from the Animation enum.

    Dependencies:
        eye_controller: EyeController instance.
    """

    action_type = ActionType.PLAY_EYE_ANIMATION

    def __init__(self, eye_controller=None, context_manager=None) -> None:
        self._eyes = eye_controller
        self._context = context_manager

    async def handle(self, action: Action) -> None:
        """
        Execute the play_eye_animation action.

        Args:
            action: Action with payload of type PlayEyeAnimationPayload.
        """
        payload: PlayEyeAnimationPayload = action.payload
        animation_name = payload.animation.upper()

        log.info("Playing eye animation: %s", animation_name)

        if self._eyes is not None:
            import asyncio
            from display.eye_controller import Animation
            try:
                anim = Animation[animation_name]
            except KeyError:
                log.warning("Unknown animation '%s' — skipping.", animation_name)
                return

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._eyes.play, anim)
        else:
            log.warning("EyeController not available — skipping animation '%s'.", animation_name)

        if self._context:
            self._context.record_action(ActionType.PLAY_EYE_ANIMATION)
