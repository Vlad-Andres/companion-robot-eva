from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from log import logger

_log = logger("eva.language_model")

# Braces, key names and quotes are tokens too. When a schema is in play the
# reply budget has to cover the wrapper as well as the words, or the object
# gets cut off before it closes — which costs the commands, since only the
# spoken part survives truncation.
_SCHEMA_TOKEN_ALLOWANCE = 48


class LanguageModelClient:
    def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        Yield reply text in pieces as the model produces them.

        `response_format` is a JSON schema the reply must satisfy. The pieces
        are then fragments of a JSON document rather than of a sentence — see
        reply_stream.py, which turns them back into speech as they arrive.
        """
        raise NotImplementedError()


class DisabledLanguageModelClient(LanguageModelClient):
    async def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        return
        yield  # pragma: no cover — makes this an async generator


class ScriptedLanguageModelClient(LanguageModelClient):
    """
    Replies with a fixed string, a few characters at a time.

    The point is the "a few characters at a time": a stub that returned the
    whole reply in one piece would never exercise sentence splitting or the
    incremental JSON reader, which are the parts most likely to be wrong. Set
    EVA_LANGUAGE_MODEL_STUB_REPLY to run the whole pipeline — commands and all
    — with no Ollama and no robot.
    """

    def __init__(self, reply: str, *, chunk_size: int = 7) -> None:
        self._reply = reply
        self._chunk_size = max(1, chunk_size)

    async def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        for start in range(0, len(self._reply), self._chunk_size):
            yield self._reply[start : start + self._chunk_size]


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_seconds: float
    max_reply_tokens: int = 80
    keep_alive: str = "30m"
    temperature: float = 0.2


class OllamaLanguageModelClient(LanguageModelClient):
    """
    Streaming Ollama client.

    Streaming is the point: waiting for a whole reply before synthesising it
    means the robot is silent for the sum of both, where streaming lets the
    first sentence be spoken while the rest is still being written.

    urllib blocks, so the response is read on a worker thread and handed back
    through a queue rather than awaited directly.
    """

    def __init__(self, cfg: OllamaConfig) -> None:
        self._cfg = cfg

    async def stream(
        self,
        *,
        system_prompt: str,
        user_text: str,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        import asyncio
        import urllib.request

        url = f"{self._cfg.base_url.rstrip('/')}/api/chat"
        num_predict = self._cfg.max_reply_tokens + (_SCHEMA_TOKEN_ALLOWANCE if response_format else 0)
        payload: Dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
            "options": {
                # A companion robot that monologues feels broken, and every
                # extra token is extra seconds before it stops talking.
                "num_predict": num_predict,
                # Structured replies want the obvious answer, not an
                # imaginative one — a creative sample is how a small model
                # invents an action name and loses the command.
                "temperature": self._cfg.temperature,
            },
            # Keep the weights resident: a cold load costs seconds on the
            # first question after a quiet spell.
            "keep_alive": self._cfg.keep_alive,
        }
        if response_format is not None:
            payload["format"] = response_format

        loop = asyncio.get_running_loop()
        pieces: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _pump() -> None:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self._cfg.timeout_seconds) as response:
                    for raw_line in response:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue
                        message = data.get("message")
                        if isinstance(message, dict):
                            content = message.get("content")
                            if isinstance(content, str) and content:
                                loop.call_soon_threadsafe(pieces.put_nowait, content)
                        if data.get("done"):
                            break
            except Exception as exc:
                _log.warning("Ollama stream error: %s", exc)
            finally:
                loop.call_soon_threadsafe(pieces.put_nowait, None)

        worker = asyncio.create_task(asyncio.to_thread(_pump))
        try:
            while True:
                piece = await pieces.get()
                if piece is None:
                    break
                yield piece
        finally:
            worker.cancel()


def build_language_model_client(
    *,
    enabled: bool,
    base_url: str,
    model: str,
    timeout_seconds: float,
    max_reply_tokens: int = 80,
    keep_alive: str = "30m",
    temperature: float = 0.2,
    stub_reply: str = "",
) -> LanguageModelClient:
    if stub_reply.strip():
        _log.info("Language model stub enabled")
        return ScriptedLanguageModelClient(stub_reply.strip())

    if not enabled:
        return DisabledLanguageModelClient()

    return OllamaLanguageModelClient(
        OllamaConfig(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_reply_tokens=max_reply_tokens,
            keep_alive=keep_alive,
            temperature=temperature,
        )
    )
