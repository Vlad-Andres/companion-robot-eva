"""
sentences.py — Cutting a token stream into speakable pieces.

Synthesis needs whole sentences to get the prosody right, but waiting for the
whole reply before speaking any of it wastes the time the model spends on the
rest. This splits the stream at the first boundary that is safely a sentence
end, so each piece can be synthesised while the next is still arriving.
"""

from __future__ import annotations

import re
from typing import Iterator, Optional

# A terminator, any closing quote or bracket, then whitespace.
_BOUNDARY = re.compile(r'[.!?]["\')\]]*\s')

# "1." and "Dr." are not sentence ends. Only the ones likely in speech.
_ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "st.", "prof.", "e.g.", "i.e.", "vs.")

# Enough to skip a stray "Hi." without holding back a real short reply like
# "I hope so!". Set this higher and the first sentence — the one that decides
# how fast Eva feels — waits for the second to finish.
MIN_SENTENCE_CHARS = 8


class SentenceAccumulator:
    """
    Feed it token pieces; it yields sentences as they complete.

    Call finish() at the end of the stream for whatever is left over.
    """

    def __init__(self, min_chars: int = MIN_SENTENCE_CHARS) -> None:
        self._buffer = ""
        self._min_chars = min_chars

    def add(self, piece: str) -> Iterator[str]:
        self._buffer += piece
        while True:
            sentence = self._take_sentence()
            if sentence is None:
                return
            yield sentence

    def finish(self) -> Optional[str]:
        """Whatever is left, if it is worth speaking."""
        remainder = self._buffer.strip()
        self._buffer = ""
        return remainder or None

    def _take_sentence(self) -> Optional[str]:
        for match in _BOUNDARY.finditer(self._buffer):
            end = match.end()
            candidate = self._buffer[:end].strip()

            if len(candidate) < self._min_chars:
                continue
            if candidate.lower().endswith(_ABBREVIATIONS):
                continue

            self._buffer = self._buffer[end:]
            return candidate
        return None
