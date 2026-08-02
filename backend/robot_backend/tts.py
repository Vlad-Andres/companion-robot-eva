from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from .log import logger

_log = logger("robot_backend.tts")


class TtsEngine:
    def synthesize_wav(self, text: str) -> Optional[bytes]:
        raise NotImplementedError()


class DisabledTtsEngine(TtsEngine):
    def synthesize_wav(self, text: str) -> Optional[bytes]:
        return None


@dataclass(frozen=True)
class PiperConfig:
    model_path: str
    config_path: str


class PiperTtsEngine(TtsEngine):
    def __init__(self, cfg: PiperConfig) -> None:
        self._cfg = cfg

    def synthesize_wav(self, text: str) -> Optional[bytes]:
        piper = shutil.which("piper")
        if not piper:
            _log.warning("Piper binary not found")
            return None
        if not os.path.exists(self._cfg.model_path):
            _log.warning("Piper model not found: %s", self._cfg.model_path)
            return None
        if not os.path.exists(self._cfg.config_path):
            _log.warning("Piper config not found: %s", self._cfg.config_path)
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            args = [piper, "--model", self._cfg.model_path, "--config", self._cfg.config_path, "--output_file", wav_path]
            proc = subprocess.run(
                args,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="ignore").strip()
                if err:
                    _log.warning("Piper error: %s", err)
                return None
            with open(wav_path, "rb") as rf:
                return rf.read()
        finally:
            try:
                os.remove(wav_path)
            except Exception:
                pass


def build_default_tts_engine(*, enabled: bool, model_path: str, config_path: str) -> TtsEngine:
    if not enabled:
        return DisabledTtsEngine()
    return PiperTtsEngine(PiperConfig(model_path=model_path, config_path=config_path))
