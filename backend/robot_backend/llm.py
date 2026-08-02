from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .log import logger

_log = logger("robot_backend.llm")


class LlmClient:
    async def chat(self, *, system_prompt: str, user_text: str) -> Optional[str]:
        raise NotImplementedError()


class DisabledLlmClient(LlmClient):
    async def chat(self, *, system_prompt: str, user_text: str) -> Optional[str]:
        return None


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    model: str
    timeout_seconds: float


class OllamaLlmClient(LlmClient):
    def __init__(self, cfg: OllamaConfig) -> None:
        self._cfg = cfg

    async def chat(self, *, system_prompt: str, user_text: str) -> Optional[str]:
        import urllib.request
        import asyncio

        url = f"{self._cfg.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._cfg.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
            "stream": False,
        }

        def _run() -> Optional[str]:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                message = data.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    return content.strip() if isinstance(content, str) else None
                return None

        try:
            return await asyncio.to_thread(_run)
        except Exception as e:
            _log.warning("Ollama chat error: %s", str(e))
            return None


def build_default_llm_client(*, enabled: bool, base_url: str, model: str, timeout_seconds: float) -> LlmClient:
    if not enabled:
        return DisabledLlmClient()
    return OllamaLlmClient(OllamaConfig(base_url=base_url, model=model, timeout_seconds=timeout_seconds))
