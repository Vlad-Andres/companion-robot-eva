from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")

_PHRASE_REPLACEMENTS: List[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(come|go|walk|move)\s+to\s+me\b"), "come here"),
    (re.compile(r"\b(come|go|walk|move)\s+here\b"), "come here"),
    (re.compile(r"\b(get|come)\s+closer\b"), "come here"),
    (re.compile(r"\bgo\s+ahead\b"), "go forward"),
    (re.compile(r"\bmove\s+ahead\b"), "move forward"),
]

_TOKEN_CANONICAL: Dict[str, str] = {
    "halt": "stop",
    "freeze": "stop",
    "pause": "stop",
    "advance": "forward",
    "ahead": "forward",
    "forwards": "forward",
    "back": "backward",
    "reverse": "backward",
    "backwards": "backward",
    "rotate": "turn",
    "spin": "turn",
}


def normalize_text(text: str) -> str:
    t = text.lower().strip()
    t = _NON_ALNUM_RE.sub(" ", t)
    t = " ".join(t.split())
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        t = pattern.sub(replacement, t)
    tokens = t.split()
    tokens = [_TOKEN_CANONICAL.get(tok, tok) for tok in tokens]
    t = " ".join(tokens)
    return t


@dataclass(frozen=True)
class ActionRule:
    key: str
    patterns: List[re.Pattern]
    actions: List[Dict]


_RULES: List[ActionRule] = [
    ActionRule(
        key="stop",
        patterns=[re.compile(r"\bstop\b")],
        actions=[
            {"type": "speak", "payload": {"text": "Stopping."}},
            {"type": "move_base", "payload": {"command": "stop"}},
        ],
    ),
    ActionRule(
        key="move_forward",
        patterns=[
            re.compile(r"\bforward\b"),
        ],
        actions=[
            {"type": "speak", "payload": {"text": "Moving forward."}},
            {"type": "move_base", "payload": {"command": "forward"}},
        ],
    ),
    ActionRule(
        key="move_back",
        patterns=[
            re.compile(r"\bbackward\b"),
        ],
        actions=[
            {"type": "speak", "payload": {"text": "Moving backward."}},
            {"type": "move_base", "payload": {"command": "backward"}},
        ],
    ),
    ActionRule(
        key="turn_left",
        patterns=[re.compile(r"\bturn\s+left\b")],
        actions=[
            {"type": "speak", "payload": {"text": "Turning left."}},
            {"type": "move_base", "payload": {"command": "turn_left"}},
        ],
    ),
    ActionRule(
        key="turn_right",
        patterns=[re.compile(r"\bturn\s+right\b")],
        actions=[
            {"type": "speak", "payload": {"text": "Turning right."}},
            {"type": "move_base", "payload": {"command": "turn_right"}},
        ],
    ),
    ActionRule(
        key="come_here",
        patterns=[re.compile(r"\bcome\s+here\b")],
        actions=[
            {"type": "speak", "payload": {"text": "Coming to you."}},
            {"type": "move_base", "payload": {"command": "come_here"}},
        ],
    ),
]


def match_action_from_text(text: str) -> Optional[Dict]:
    t = normalize_text(text)
    if not t:
        return None

    for rule in _RULES:
        if any(p.search(t) for p in rule.patterns):
            return {"key": rule.key, "actions": rule.actions}

    return None


@dataclass(frozen=True)
class IntentHint:
    key: str
    eye_expression: str


def match_intent_hint_from_text(text: str) -> Optional[IntentHint]:
    t = normalize_text(text)
    if not t:
        return None

    tokens = set(t.split())

    if "turn" in tokens and "left" not in tokens and "right" not in tokens:
        return IntentHint(key="turn_pending", eye_expression="saccade")

    if "move" in tokens or "go" in tokens or "drive" in tokens:
        if "forward" not in tokens and "backward" not in tokens and "left" not in tokens and "right" not in tokens:
            return IntentHint(key="move_pending", eye_expression="saccade")

    if "come" in tokens and "here" not in tokens:
        return IntentHint(key="come_pending", eye_expression="saccade")

    return None
