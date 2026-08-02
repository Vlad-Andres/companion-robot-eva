from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from action_rules import match_action_from_text
from actions import validate_command


@dataclass(frozen=True)
class PlanResult:
    commands: List[Dict[str, Any]]
    memory_items: List[Dict[str, Any]]
    language_model_input_text: Optional[str] = None
    # Which rule matched, e.g. "turn_left". None when the utterance was not a
    # known command; used as the training label by the dataset recorder.
    rule_key: Optional[str] = None


def plan_from_transcript(text: str) -> PlanResult:
    """
    Turn one transcript into commands, or hand it to the language model.

    A matching rule wins outright; anything else becomes dialogue.
    """
    rule = match_action_from_text(text)
    if rule is None:
        return PlanResult(commands=[], memory_items=[], language_model_input_text=text)

    commands = [c for c in map(validate_command, rule.commands) if c is not None]
    if not commands:
        return PlanResult(commands=[], memory_items=[], language_model_input_text=text)

    return PlanResult(
        commands=commands,
        memory_items=[{"type": "utterance", "text": text}],
        language_model_input_text=None,
        rule_key=rule.key,
    )
