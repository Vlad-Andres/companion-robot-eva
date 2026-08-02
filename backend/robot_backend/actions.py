from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from .protocol import ActionGroup


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    group: ActionGroup
    args_schema: Dict[str, Any]
    description: str


_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(
        name="speak",
        group="speak",
        args_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        description="Speak the provided text.",
    ),
    ActionDefinition(
        name="move_base",
        group="move",
        args_schema={
            "type": "object",
            "properties": {"command": {"type": "string", "enum": ["stop", "forward", "backward", "turn_left", "turn_right", "come_here"]}},
            "required": ["command"],
        },
        description="Low-level base movement command.",
    ),
    ActionDefinition(
        name="go_to",
        group="go_to",
        args_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}},
        },
        description="Navigate to a named target or coordinates.",
    ),
    ActionDefinition(
        name="memory_note",
        group="memory",
        args_schema={"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object"}}}, "required": ["items"]},
        description="Suggestion payload for the robot to store in memory later.",
    ),
]


def list_actions() -> List[Dict[str, Any]]:
    return [
        {"name": a.name, "group": a.group, "args_schema": a.args_schema, "description": a.description}
        for a in _ACTIONS
    ]


def action_group(name: str) -> Optional[ActionGroup]:
    for a in _ACTIONS:
        if a.name == name:
            return a.group
    return None


MoveCommand = Literal["stop", "forward", "backward", "turn_left", "turn_right", "come_here"]


def command_from_rule_action(action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = action.get("type")
    payload = action.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    if t == "speak":
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return {"name": "speak", "group": "speak", "args": {"text": text.strip()}}
        return None

    if t == "move_base":
        cmd = payload.get("command")
        if isinstance(cmd, str) and cmd in {"stop", "forward", "backward", "turn_left", "turn_right", "come_here"}:
            return {"name": "move_base", "group": "move", "args": {"command": cmd}}
        return None

    return None
