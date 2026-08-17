"""
actions/action_types.py — Typed action definitions.

Runtime handlers and behaviors dispatch action objects of the form:
    {"type": "set_eye_expression", "payload": {"expression": "happy"}}

This module defines:
  - ActionType enum: all valid action type strings
  - One dataclass per action type (the payload)
  - Action: the top-level container
  - parse_action(): factory that converts raw dict → typed Action

To add a new action type:
  1. Add a member to ActionType.
  2. Define a PayloadXxx dataclass below.
  3. Register it in _ACTION_REGISTRY at the bottom.
  4. Write a handler in actions/ that handles it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type


# ---------------------------------------------------------------------------
# Action type registry
# ---------------------------------------------------------------------------


class ActionType(str, enum.Enum):
    """
    All supported action types.

    The string value matches the "type" field of the dispatched action dict.
    """
    SET_EYE_EXPRESSION = "set_eye_expression"
    PLAY_EYE_ANIMATION = "play_eye_animation"
    MOVE_BASE = "move_base"


# ---------------------------------------------------------------------------
# Payload dataclasses — one per ActionType
# ---------------------------------------------------------------------------


@dataclass
class SetEyeExpressionPayload:
    """
    Payload for the SET_EYE_EXPRESSION action.

    Attributes:
        expression: Expression name. Must match an Animation member name
                    (e.g. "happy", "sleep", "blink_short").
    """
    expression: str


@dataclass
class PlayEyeAnimationPayload:
    """
    Payload for the PLAY_EYE_ANIMATION action.

    Plays a one-shot eye animation sequence by name.

    Attributes:
        animation: Animation name matching Animation enum member
                   (e.g. "WAKEUP", "BLINK_LONG", "SACCADE_RANDOM").
    """
    animation: str


@dataclass
class MoveBasePayload:
    """
    Payload for the MOVE_BASE action.

    Attributes:
        command: One of the movements in the server's action registry —
                 stop, forward, backward, turn_left, turn_right, come_here.
                 The vocabulary is defined once, in server/actions.py, and
                 arrives here already validated against it.
    """
    command: str


# ---------------------------------------------------------------------------
# Top-level Action container
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """
    A single structured action to execute.

    Attributes:
        type:    ActionType string identifying which action to execute.
        payload: Typed payload dataclass for this action type.
        raw:     Original raw dict, for debugging.
    """
    type: str
    payload: Any
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry mapping type string → payload class
# ---------------------------------------------------------------------------

_ACTION_REGISTRY: Dict[str, Type] = {
    ActionType.SET_EYE_EXPRESSION: SetEyeExpressionPayload,
    ActionType.PLAY_EYE_ANIMATION: PlayEyeAnimationPayload,
    ActionType.MOVE_BASE: MoveBasePayload,
}


# ---------------------------------------------------------------------------
# Parser / factory
# ---------------------------------------------------------------------------


def parse_action(raw: Dict[str, Any]) -> Action:
    """
    Parse a raw action dict into a typed Action.

    Args:
        raw: A dict with at least "type" and optionally "payload".
             Example: {"type": "set_eye_expression", "payload": {"expression": "happy"}}

    Returns:
        A fully typed Action instance.

    Raises:
        ValueError: If the "type" key is missing or unknown.
        TypeError:  If the payload fields don't match the expected dataclass.

    Example:
        action = parse_action({"type": "set_eye_expression", "payload": {"expression": "happy"}})
        # action.type == "set_eye_expression"
        # action.payload.expression == "happy"
    """
    action_type = raw.get("type")
    if not action_type:
        raise ValueError(f"Action dict is missing 'type' key: {raw!r}")

    payload_class = _ACTION_REGISTRY.get(action_type)
    if payload_class is None:
        raise ValueError(
            f"Unknown action type '{action_type}'. "
            f"Registered types: {list(_ACTION_REGISTRY.keys())}"
        )

    raw_payload = raw.get("payload", {})
    try:
        payload = payload_class(**raw_payload)
    except TypeError as exc:
        raise TypeError(
            f"Invalid payload for action type '{action_type}': {raw_payload!r} — {exc}"
        ) from exc

    return Action(type=action_type, payload=payload, raw=raw)
