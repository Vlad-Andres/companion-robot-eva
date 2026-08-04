from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from log import logger

_log = logger("eva.language_model")


class LanguageModelClient:
    def stream(self, *, system_prompt: str, user_text: str) -> AsyncIterator[str]:
        """Yield reply text in pieces as the model produces them."""
        raise NotImplementedError()


class DisabledLanguageModelClient(LanguageModelClient):
    async def stream(self, *, system_prompt: str, user_text: str) -> AsyncIterator[str]:
        return
        yield  # pragma: no cover — makes this an async generator


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_seconds: float
    max_reply_tokens: int = 80
    keep_alive: str = "30m"


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

    async def stream(self, *, system_prompt: str, user_text: str) -> AsyncIterator[str]:
        import asyncio
        import urllib.request

        url = f"{self._cfg.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
            # A companion robot that monologues feels broken, and every extra
            # token is extra seconds before it stops talking.
            "options": {"num_predict": self._cfg.max_reply_tokens},
            # Keep the weights resident: a cold load costs seconds on the
            # first question after a quiet spell.
            "keep_alive": self._cfg.keep_alive,
        }

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
) -> LanguageModelClient:
    if not enabled:
        return DisabledLanguageModelClient()
    return OllamaLanguageModelClient(
        OllamaConfig(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_reply_tokens=max_reply_tokens,
            keep_alive=keep_alive,
        )
    )
