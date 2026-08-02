from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

from log import logger

_log = logger("eva.text_to_speech")


class TextToSpeechEngine:
    def synthesize_wav(self, text: str) -> Optional[bytes]:
        raise NotImplementedError()


class DisabledTextToSpeechEngine(TextToSpeechEngine):
    def synthesize_wav(self, text: str) -> Optional[bytes]:
        return None


def _run_to_wav(args: list[str], *, stdin: Optional[bytes], label: str) -> Optional[bytes]:
    """Run a synthesiser that writes a WAV to the path given as its last argument."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        wav_path = handle.name
    try:
        process = subprocess.run(
            [arg.replace("{out}", wav_path) for arg in args],
            input=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            error = process.stderr.decode("utf-8", errors="ignore").strip()
            if error:
                _log.warning("%s error: %s", label, error)
            return None
        with open(wav_path, "rb") as wav_file:
            data = wav_file.read()
        return data or None
    except Exception as exc:
        _log.warning("%s failed: %s", label, exc)
        return None
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


@dataclass(frozen=True)
class PiperConfig:
    model_path: str
    config_path: str


class PiperTextToSpeechEngine(TextToSpeechEngine):
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

        return _run_to_wav(
            [piper, "--model", self._cfg.model_path, "--config", self._cfg.config_path, "--output_file", "{out}"],
            stdin=text.encode("utf-8"),
            label="Piper",
        )


class MacSayTextToSpeechEngine(TextToSpeechEngine):
    """
    macOS's built-in `say`. Lower quality than Piper but needs no installation,
    which makes it a dependable fallback when the Piper binary is missing or broken.
    """

    def synthesize_wav(self, text: str) -> Optional[bytes]:
        say = shutil.which("say")
        if not say:
            _log.warning("`say` is only available on macOS")
            return None
        return _run_to_wav(
            [say, "-o", "{out}", "--data-format=LEI16@22050", text],
            stdin=None,
            label="say",
        )


def _works(engine: TextToSpeechEngine) -> bool:
    """Synthesise a short phrase to prove the engine is actually usable."""
    try:
        return bool(engine.synthesize_wav("test"))
    except Exception:
        return False


def build_text_to_speech_engine(
    *,
    enabled: bool,
    model_path: str,
    config_path: str,
    engine: str = "auto",
) -> TextToSpeechEngine:
    """
    Choose a synthesiser.

    `engine` is one of: auto, piper, macos_say, off.

    "auto" prefers Piper and falls back to `say`, but only after checking that the
    chosen engine really produces audio — Piper installs successfully on macOS while
    still failing at runtime (its bundled espeak data is looked up at a path baked in
    when the wheel was built), and a startup check turns that into one clear log line
    instead of silence during a conversation.
    """
    if not enabled or engine == "off":
        return DisabledTextToSpeechEngine()

    piper = PiperTextToSpeechEngine(PiperConfig(model_path=model_path, config_path=config_path))

    if engine == "piper":
        return piper
    if engine == "macos_say":
        return MacSayTextToSpeechEngine()

    if _works(piper):
        _log.info("Text to speech: piper")
        return piper

    say = MacSayTextToSpeechEngine()
    if _works(say):
        _log.warning("Piper unavailable; falling back to macOS `say`")
        return say

    _log.warning("No working text-to-speech engine; Eva will stay silent")
    return DisabledTextToSpeechEngine()
