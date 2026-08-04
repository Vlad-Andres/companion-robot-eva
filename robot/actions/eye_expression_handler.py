"""
actions/eye_expression_handler.py — Handlers for eye animation actions.

Handles both:
  - "set_eye_expression": sets a persistent expression (happy, sleep, etc.)
  - "play_eye_animation": plays a one-shot animation sequence (wakeup, blink, etc.)

Both resolve their name to an Animation member and hand it to
EyeController.play(), which already dispatches by name.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from actions.action_types import Action, ActionType
from actions.base_action_handler import BaseActionHandler
from utils.logger import get_logger

log = get_logger(__name__)


# Spoken names that don't match an Animation member one-to-one.
_ANIMATION_ALIASES = {
    "neutral": "RESET",
    "default": "RESET",
    "blink": "BLINK_SHORT",
    "saccade": "SACCADE_RANDOM",
}

_BLINK_ANIMATIONS = frozenset({"BLINK_SHORT", "BLINK_LONG"})


class DisplayRateLimit:
    """
    Shared minimum interval between eye actions.

    One instance is shared by every eye handler: the limit protects the I2C
    display itself, so expression and animation actions must draw from the
    same budget rather than each getting their own.
    """

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_action_at: float = 0.0

    async def allow(self) -> bool:
        """Claim the next slot, or return False if one was used too recently."""
        async with self._lock:
            now = time.monotonic()
            if (now - self._last_action_at) < self._min_interval:
                return False
            self._last_action_at = now
            return True


def _resolve_animation(name: str):
    """Map an expression or animation name to an Animation member, or None."""
    from display.eye_controller import Animation

    key = str(name or "").strip().lower()
    if not key:
        return None
    try:
        return Animation[_ANIMATION_ALIASES.get(key, key.upper())]
    except KeyError:
        return None


class _EyeActionHandler(BaseActionHandler):
    """
    Shared implementation for the two eye action types.

    Subclasses set action_type, the payload field to read the name from, and
    whether an unrecognised name falls back to a neutral face or is skipped.
    """

    payload_field: str
    unknown_name_fallback: Optional[str] = None

    def __init__(
        self,
        eye_controller=None,
        audio_output=None,
        rate_limit: Optional[DisplayRateLimit] = None,
    ) -> None:
        """
        Args:
            eye_controller: EyeController instance, or None when absent.
            audio_output:   AudioOutput for the blink sound effect.
            rate_limit:     Shared DisplayRateLimit; one is created if omitted.
        """
        self._eyes = eye_controller
        self._audio = audio_output
        self._rate_limit = rate_limit or DisplayRateLimit()

    async def handle(self, action: Action) -> None:
        if not await self._rate_limit.allow():
            return

        name = getattr(action.payload, self.payload_field)
        animation = _resolve_animation(name)

        if animation is None:
            if self.unknown_name_fallback is None:
                log.warning("Unknown eye animation '%s' — skipping.", name)
                return
            log.warning("Unknown eye expression '%s' — falling back to neutral.", name)
            animation = _resolve_animation(self.unknown_name_fallback)

        if self._eyes is None:
            log.warning("EyeController not available — skipping '%s'.", animation.name)
            return

        log.info("Eye action: %s", animation.name)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._eyes.play, animation)

        if animation.name in _BLINK_ANIMATIONS and self._audio is not None:
            self._audio.play_blink()


class EyeExpressionHandler(_EyeActionHandler):
    """Handles "set_eye_expression" — an unknown name resets to neutral."""

    action_type = ActionType.SET_EYE_EXPRESSION
    payload_field = "expression"
    unknown_name_fallback = "neutral"


class EyeAnimationHandler(_EyeActionHandler):
    """Handles "play_eye_animation" — an unknown name is skipped."""

    action_type = ActionType.PLAY_EYE_ANIMATION
    payload_field = "animation"
