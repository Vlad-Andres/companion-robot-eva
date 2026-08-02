from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from action_rules import match_action_from_text

from actions import command_from_rule_action


@dataclass(frozen=True)
class PlanResult:
    commands: List[Dict[str, Any]]
    memory_items: List[Dict[str, Any]]
    language_model_input_text: Optional[str] = None


def plan_from_transcript(text: str) -> PlanResult:
    rule = match_action_from_text(text)
    commands: List[Dict[str, Any]] = []
    memory_items: List[Dict[str, Any]] = []

    if isinstance(rule, dict):
        actions = rule.get("actions")
        if isinstance(actions, list):
            for a in actions:
                if isinstance(a, dict):
                    command = command_from_rule_action(a)
                    if command is not None:
                        commands.append(command)

    if not commands:
        return PlanResult(commands=[], memory_items=[], language_model_input_text=text)

    memory_items.append({"type": "utterance", "text": text})
    return PlanResult(commands=commands, memory_items=memory_items, language_model_input_text=None)
