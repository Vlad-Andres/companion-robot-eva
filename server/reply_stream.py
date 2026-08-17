"""
reply_stream.py — Reading a reply that is still being written.

Constraining the model to a `{"say": ..., "commands": [...]}` schema is what
lets Eva act on a conversation instead of only answering it. The cost, taken
naively, is the thing the streaming pipeline was built to avoid: JSON cannot be
parsed until the closing brace arrives, so Eva would go quiet for the whole
generation and then say everything at once.

The standard advice for streamed structured output is to stream for output and
accumulate for parsing. That is exactly what this does. The `say` value is a
string, and a string can be read character by character long before the object
around it is complete — so speech starts on the first few tokens, while
`commands` is parsed from the finished object at the end.

Three things fall out of it for free:

* A truncated reply — the token budget running out mid-object — is still
  spoken, because the spoken part was never waiting on the closing brace.
  Ollama's grammar guarantees the shape of what it emits, not that it finishes.
* A model that ignores the schema and answers in plain prose is handled by the
  same code path: if the reply does not begin as JSON, every piece is speech.
* Eva never reads raw JSON aloud, whether or not a schema was requested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

# Give up on identifying the reply after this much, and treat it as speech.
# Only whitespace and an optional code fence are expected before the brace.
_DETECT_LIMIT = 200

_MODE_DETECT = "detect"
_MODE_TEXT = "text"
_MODE_JSON = "json"


@dataclass(frozen=True)
class ReplyOutcome:
    """What the finished reply turned out to be."""

    commands: List[Dict[str, Any]] = field(default_factory=list)
    structured: bool = False
    # True when the reply started as JSON but never closed — almost always the
    # token budget. The speech survived; any commands did not.
    truncated: bool = False
    # Speech the stream was still holding when it ended: a reply too short to
    # ever look like JSON is only recognised as speech once it stops.
    text: str = ""


def _scan_string_fragment(fragment: str) -> tuple[str, int, bool]:
    """
    Read as much of a JSON string body as is safely complete.

    Returns the decoded text, how many raw characters it consumed, and whether
    the closing quote was reached. A trailing half-written escape (`\\` alone,
    or `\\u00` so far) is left unconsumed rather than guessed at, so the next
    piece completes it.
    """
    index = 0
    while index < len(fragment):
        char = fragment[index]
        if char == '"':
            break
        if char != "\\":
            index += 1
            continue
        # An escape needs its payload before it can be decoded: one character,
        # or four hex digits after a \u.
        if index + 1 >= len(fragment):
            break
        width = 6 if fragment[index + 1] == "u" else 2
        if index + width > len(fragment):
            break
        index += width

    raw = fragment[:index]
    closed = index < len(fragment) and fragment[index] == '"'
    if not raw:
        return "", index + (1 if closed else 0), closed

    try:
        text = json.loads(f'"{raw}"')
    except ValueError:
        # A control character the grammar should have escaped. Hold rather than
        # emit rubbish; if the stream ends here the text is dropped, which is
        # the right trade against speaking a decoding artefact out loud.
        return "", 0, False

    return text, index + (1 if closed else 0), closed


class ReplyStream:
    """
    Feed it raw model output; it yields text that is ready to be spoken.

    Call finish() at the end for the parsed commands.
    """

    def __init__(self) -> None:
        self._mode = _MODE_DETECT
        self._pending = ""       # undecided prefix, while detecting
        self._raw = ""           # the whole JSON reply, for the final parse
        self._say_cursor: Optional[int] = None   # where the say body starts in _raw
        self._say_closed = False

    def add(self, piece: str) -> Iterator[str]:
        if not piece:
            return

        if self._mode == _MODE_DETECT:
            self._pending += piece
            decided = self._detect()
            if not decided:
                return
            piece, self._pending = self._pending, ""

        if self._mode == _MODE_TEXT:
            yield piece
            return

        self._raw += piece
        yield from self._read_say()

    def finish(self) -> ReplyOutcome:
        """Parse whatever the stream turned out to be."""
        if self._mode == _MODE_DETECT:
            # It stopped before it ever looked like JSON, so it was speech —
            # a one-word answer reaches here.
            leftover, self._pending = self._pending, ""
            self._mode = _MODE_TEXT
            return ReplyOutcome(text=leftover)

        if self._mode != _MODE_JSON:
            return ReplyOutcome()

        try:
            parsed = json.loads(self._raw)
        except ValueError:
            return ReplyOutcome(structured=True, truncated=True)

        if not isinstance(parsed, dict):
            return ReplyOutcome(structured=True, truncated=True)

        raw_commands = parsed.get("commands")
        commands = [c for c in raw_commands if isinstance(c, dict)] if isinstance(raw_commands, list) else []
        return ReplyOutcome(commands=commands, structured=True)

    # ------------------------------------------------------------------

    def _detect(self) -> bool:
        """Decide whether this reply is JSON. True once the mode is settled."""
        stripped = self._pending.lstrip()

        # A fenced block is a model ignoring the "no markdown" instruction
        # rather than a different kind of reply. Step over the fence line.
        if stripped.startswith("```"):
            newline = stripped.find("\n")
            if newline == -1:
                return self._give_up_detecting()
            stripped = stripped[newline + 1 :].lstrip()
            self._pending = stripped

        if not stripped:
            return self._give_up_detecting()

        if stripped.startswith("{"):
            self._pending = stripped
            self._mode = _MODE_JSON
            return True

        self._mode = _MODE_TEXT
        return True

    def _give_up_detecting(self) -> bool:
        """Nothing but whitespace or an unclosed fence so far. Wait, then relent."""
        if len(self._pending) <= _DETECT_LIMIT:
            return False
        self._mode = _MODE_TEXT
        return True

    def _read_say(self) -> Iterator[str]:
        """Emit whatever of the `say` value has arrived since the last call."""
        if self._say_closed:
            return

        if self._say_cursor is None:
            start = _find_say_body(self._raw)
            if start is None:
                return
            self._say_cursor = start

        text, consumed, closed = _scan_string_fragment(self._raw[self._say_cursor :])
        self._say_cursor += consumed
        self._say_closed = closed
        if text:
            yield text


def _find_say_body(raw: str) -> Optional[int]:
    """
    Index just past the opening quote of the `say` value, if it has arrived.

    Deliberately literal: the grammar emits the key exactly as the schema
    declares it, and a hand-rolled scan for one known key is easier to be sure
    of than a partial-JSON parser.
    """
    key = raw.find('"say"')
    if key == -1:
        return None

    index = key + len('"say"')
    while index < len(raw) and raw[index].isspace():
        index += 1
    if index >= len(raw) or raw[index] != ":":
        return None
    index += 1
    while index < len(raw) and raw[index].isspace():
        index += 1
    if index >= len(raw) or raw[index] != '"':
        return None
    return index + 1
