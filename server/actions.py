from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# The movement vocabulary, defined once. The JSON schema below and the
# validation in validate_command() both read from it, so adding a movement
# means editing this tuple alone.
MOVE_COMMANDS = ("stop", "forward", "backward", "turn_left", "turn_right", "come_here")


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    args_schema: Dict[str, Any]
    description: str


_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(
        name="speak",
        args_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        description="Speak the provided text.",
    ),
    ActionDefinition(
        name="move_base",
        args_schema={
            "type": "object",
            "properties": {"command": {"type": "string", "enum": list(MOVE_COMMANDS)}},
            "required": ["command"],
        },
        description="Low-level base movement command.",
    ),
]


def list_actions() -> List[Dict[str, Any]]:
    """The action registry, as served by GET /v1/actions."""
    return [
        {"name": a.name, "args_schema": a.args_schema, "description": a.description}
        for a in _ACTIONS
    ]


def validate_command(command: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Check one {name, args} command against the registry.

    Returns the command with its arguments normalised, or None if the name is
    unknown or the arguments don't fit. Everything sent to the robot passes
    through here, so a malformed rule or model reply cannot reach the wire.
    """
    name = command.get("name")
    args = command.get("args")
    if not isinstance(name, str) or not isinstance(args, dict):
        return None

    if name == "speak":
        text = args.get("text")
        if isinstance(text, str) and text.strip():
            return {"name": "speak", "args": {"text": text.strip()}}
        return None

    if name == "move_base":
        movement = args.get("command")
        if isinstance(movement, str) and movement in MOVE_COMMANDS:
            return {"name": "move_base", "args": {"command": movement}}
        return None

    return None
