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
    key: str          # Also the training label used by the dataset recorder.
    patterns: List[re.Pattern]
    commands: List[Dict]   # Wire-shape {name, args} — see actions.py.


_RULES: List[ActionRule] = [
    ActionRule(
        key="stop",
        patterns=[re.compile(r"\bstop\b")],
        commands=[
            {"name": "speak", "args": {"text": "Stopping."}},
            {"name": "move_base", "args": {"command": "stop"}},
        ],
    ),
    ActionRule(
        key="move_forward",
        patterns=[re.compile(r"\bforward\b")],
        commands=[
            {"name": "speak", "args": {"text": "Moving forward."}},
            {"name": "move_base", "args": {"command": "forward"}},
        ],
    ),
    ActionRule(
        key="move_back",
        patterns=[re.compile(r"\bbackward\b")],
        commands=[
            {"name": "speak", "args": {"text": "Moving backward."}},
            {"name": "move_base", "args": {"command": "backward"}},
        ],
    ),
    ActionRule(
        key="turn_left",
        patterns=[re.compile(r"\bturn\s+left\b")],
        commands=[
            {"name": "speak", "args": {"text": "Turning left."}},
            {"name": "move_base", "args": {"command": "turn_left"}},
        ],
    ),
    ActionRule(
        key="turn_right",
        patterns=[re.compile(r"\bturn\s+right\b")],
        commands=[
            {"name": "speak", "args": {"text": "Turning right."}},
            {"name": "move_base", "args": {"command": "turn_right"}},
        ],
    ),
    ActionRule(
        key="come_here",
        patterns=[re.compile(r"\bcome\s+here\b")],
        commands=[
            {"name": "speak", "args": {"text": "Coming to you."}},
            {"name": "move_base", "args": {"command": "come_here"}},
        ],
    ),
]


def match_action_from_text(text: str) -> Optional[ActionRule]:
    t = normalize_text(text)
    if not t:
        return None

    for rule in _RULES:
        if any(p.search(t) for p in rule.patterns):
            return rule

    return None
