from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from capabilities import RobotCapabilities

# The movement vocabulary, defined once. The JSON schema below and the
# validation in validate_command() both read from it, so adding a movement
# means editing this tuple alone.
MOVE_COMMANDS = ("stop", "forward", "backward", "turn_left", "turn_right", "come_here")


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    args_schema: Dict[str, Any]
    description: str
    # Actuators the robot must have declared for this action to be legal.
    # Empty means every robot can do it.
    requires: tuple[str, ...] = ()
    # False for actions the server fulfils itself. `speak` is the one case:
    # the model writes speech into its `say` field, so offering it a `speak`
    # command as well would give it two ways to say the same thing.
    model_callable: bool = True


_ACTIONS: List[ActionDefinition] = [
    ActionDefinition(
        name="speak",
        args_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        description="Speak the provided text.",
        requires=("speaker",),
        model_callable=False,
    ),
    ActionDefinition(
        name="move_base",
        args_schema={
            "type": "object",
            "properties": {"command": {"type": "string", "enum": list(MOVE_COMMANDS)}},
            "required": ["command"],
        },
        description="Move the base. Use this whenever the reply involves going somewhere or stopping.",
        requires=("base",),
    ),
]


def list_actions() -> List[Dict[str, Any]]:
    """The whole registry, as served by GET /v1/actions."""
    return [
        {
            "name": a.name,
            "args_schema": a.args_schema,
            "description": a.description,
            "requires": list(a.requires),
        }
        for a in _ACTIONS
    ]


def available_actions(capabilities: RobotCapabilities) -> List[ActionDefinition]:
    """The subset of the registry this robot has the hardware for."""
    return [a for a in _ACTIONS if all(capabilities.has_actuator(r) for r in a.requires)]


def available_action_names(capabilities: RobotCapabilities) -> Set[str]:
    return {a.name for a in available_actions(capabilities)}


def describe_actions(capabilities: RobotCapabilities) -> List[Dict[str, Any]]:
    """What this robot may be sent, for the capability acknowledgement."""
    return [
        {"name": a.name, "args_schema": a.args_schema, "description": a.description}
        for a in available_actions(capabilities)
    ]


def validate_command(command: Dict[str, Any], allowed: Optional[Iterable[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Check one {name, args} command against the registry.

    Returns the command with its arguments normalised, or None if the name is
    unknown, the arguments don't fit, or the connected robot lacks the hardware
    (`allowed` — omit it to check against the registry alone). Everything sent
    to the robot passes through here, so a malformed rule or model reply cannot
    reach the wire.
    """
    name = command.get("name")
    args = command.get("args")
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    if allowed is not None and name not in set(allowed):
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


def _command_schema(actions: List[ActionDefinition]) -> Dict[str, Any]:
    """
    One command, as a schema.

    Ollama compiles the schema into a token grammar, and support for `anyOf`
    across that compiler has been inconsistent between releases — so the union
    is only emitted when there is genuinely more than one action to choose
    between. With a single action the schema is the action itself, which every
    version handles. validate_command() is the real gate underneath either way:
    the grammar guarantees the shape, not the meaning.
    """
    variants = [
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "enum": [action.name]},
                "args": action.args_schema,
            },
            "required": ["name", "args"],
        }
        for action in actions
    ]
    return variants[0] if len(variants) == 1 else {"anyOf": variants}


def reply_schema(capabilities: RobotCapabilities) -> Optional[Dict[str, Any]]:
    """
    The JSON schema the language model fills in, built from this robot's hardware.

    `say` is declared first on purpose. The grammar follows property order, so
    the spoken part is generated before the command list — which is what lets
    the reply start being spoken while the model is still deciding whether to
    move (see reply_stream.py), and what makes a truncated reply still speakable.

    Returns None when the robot can perform nothing the model could call. There
    is no point constraining a reply that can only ever be words: plain text
    streams sooner and every model handles it.
    """
    callable_actions = [a for a in available_actions(capabilities) if a.model_callable]
    if not callable_actions:
        return None

    return {
        "type": "object",
        "properties": {
            "say": {
                "type": "string",
                "description": "What Eva says out loud: one or two short spoken sentences.",
            },
            "commands": {
                "type": "array",
                "description": "Actions to perform. Empty when the reply is only conversation.",
                "items": _command_schema(callable_actions),
            },
        },
        "required": ["say", "commands"],
    }


def describe_actions_for_prompt(capabilities: RobotCapabilities) -> str:
    """
    The action vocabulary as a prompt fragment.

    The schema already makes an unavailable action unspeakable; this tells the
    model what the available names mean, so it picks the right one instead of
    discovering the vocabulary by rejection. Ollama's own guidance is to ground
    the schema in the prompt as well as the grammar.
    """
    lines = []
    for action in available_actions(capabilities):
        if not action.model_callable:
            continue
        detail = []
        for arg_name, arg_schema in action.args_schema.get("properties", {}).items():
            options = arg_schema.get("enum")
            detail.append(f"{arg_name}={'|'.join(options)}" if options else f"{arg_name}:{arg_schema.get('type', 'string')}")
        lines.append(f"- {action.name}({', '.join(detail)}) — {action.description}")
    return "\n".join(lines)
