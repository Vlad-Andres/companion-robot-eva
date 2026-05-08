"""
actions/eye_expression_handler.py — Handler for eye animation actions.

Handles both:
  - "set_eye_expression": sets a persistent expression (happy, sleep, etc.)
  - "play_eye_animation": plays a one-shot animation sequence (wakeup, blink, etc.)

Delegates to the EyeController from display/eye_controller.py.
"""

from __future__ import annotations

import asyncio
import time

from actions.action_types import (
    Action,
    ActionType,
    PlayEyeAnimationPayload,
    SetEyeExpressionPayload,
)
from actions.base_action_handler import BaseActionHandler
from utils.logger import get_logger

log = get_logger(__name__)

_EYE_ACTION_LOCK = asyncio.Lock()
_LAST_EYE_ACTION_AT: float = 0.0
_MIN_EYE_ACTION_INTERVAL_SECONDS = 1.0


async def _reserve_eye_slot() -> bool:
    global _LAST_EYE_ACTION_AT
    async with _EYE_ACTION_LOCK:
        now = time.monotonic()
        if (now - _LAST_EYE_ACTION_AT) < _MIN_EYE_ACTION_INTERVAL_SECONDS:
            return False
        _LAST_EYE_ACTION_AT = now
        return True


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

    def __init__(self, eye_controller=None, context_manager=None, audio_config=None) -> None:
        """
        Args:
            eye_controller:  EyeController instance.
            context_manager: ContextManager for state updates.
            audio_config:    AudioConfig for sound effects.
        """
        self._eyes = eye_controller
        self._context = context_manager
        self._audio = audio_config

    async def handle(self, action: Action) -> None:
        """
        Execute the set_eye_expression action.

        Args:
            action: Action with payload of type SetEyeExpressionPayload.
        """
        if not await _reserve_eye_slot():
            return

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
                "curious": self._eyes.curious,
                "confused": self._eyes.confused,
                "thinking": self._eyes.thinking,
                "impatient": self._eyes.impatient,
            }

            method = expression_map.get(expression)
            if method is None:
                log.warning("Unknown expression '%s' — falling back to neutral.", expression)
                method = self._eyes.reset

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, method)

            # Play blink sound if this was a blink expression.
            if expression in ("blink", "blink_short", "blink_long"):
                self._play_blink_sound()
        else:
            log.warning("EyeController not available — skipping display for '%s'.", expression)

        # Always update context, even when display hardware is absent.
        if self._context:
            self._context.update_expression(expression)
            self._context.record_action(ActionType.SET_EYE_EXPRESSION)


    def _play_blink_sound(self) -> None:
        """Helper to play the blink sound if enabled."""
        if self._audio and self._audio.enabled and self._audio.blink_sound:
            from utils.audio import play_sound
            play_sound(self._audio.blink_sound, device=self._audio.device)


class EyeAnimationHandler(BaseActionHandler):
    """
    Handles "play_eye_animation" actions.

    Plays a one-shot named animation from the Animation enum.

    Dependencies:
        eye_controller: EyeController instance.
    """

    action_type = ActionType.PLAY_EYE_ANIMATION

    def __init__(self, eye_controller=None, context_manager=None, audio_config=None) -> None:
        self._eyes = eye_controller
        self._context = context_manager
        self._audio = audio_config

    async def handle(self, action: Action) -> None:
        """
        Execute the play_eye_animation action.

        Args:
            action: Action with payload of type PlayEyeAnimationPayload.
        """
        if not await _reserve_eye_slot():
            return

        payload: PlayEyeAnimationPayload = action.payload
        animation_name = payload.animation.upper()

        log.info("Playing eye animation: %s", animation_name)

        if self._eyes is not None:
            from display.eye_controller import Animation
            try:
                anim = Animation[animation_name]
            except KeyError:
                log.warning("Unknown animation '%s' — skipping.", animation_name)
                return

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._eyes.play, anim)

            # Play blink sound if this was a blink animation.
            if animation_name in ("BLINK_SHORT", "BLINK_LONG"):
                self._play_blink_sound()
        else:
            log.warning("EyeController not available — skipping animation '%s'.", animation_name)

    def _play_blink_sound(self) -> None:
        """Helper to play the blink sound if enabled."""
        if self._audio and self._audio.enabled and self._audio.blink_sound:
            from utils.audio import play_sound
            play_sound(self._audio.blink_sound, device=self._audio.device)
