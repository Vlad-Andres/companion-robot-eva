"""
utils/audio.py — Every sound the robot makes goes out through here.

One AudioOutput instance owns the audio settings and is injected wherever
sound is played, so the device, the volume and the on/off switch live in
exactly one place.

Volume is the mixer's job, applied once by apply_volume() at startup. Playback
never rescales the samples: doing both at once is how the output ended up at
0.25% of full scale, and scaling int16 samples down also throws away bit depth
that the speaker never gets back.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from config import AudioConfig
from utils.logger import get_logger

log = get_logger(__name__)

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


class AudioOutput:
    """
    Speaker output: sound effects and synthesized speech.

    Usage:
        audio = AudioOutput(config.audio)
        audio.apply_volume()        # once, at startup
        audio.play_startup()        # fire and forget
        audio.play_speech(wav)      # blocks until finished
    """

    def __init__(self, config: AudioConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Volume — the single place output level is decided
    # ------------------------------------------------------------------

    def apply_volume(self) -> None:
        """
        Set the mixer to the configured level.

        Called once at startup. The mixer attenuates after the DAC, so the
        audio keeps its full dynamic range no matter how low this is set.
        """
        if not self.config.enabled:
            return

        volume = max(0, min(100, int(self.config.volume_percent)))
        args = ["amixer", "-q"]
        if self.config.mixer_card is not None:
            args += ["-c", str(self.config.mixer_card)]
        else:
            args += ["-D", self.config.device or "default"]

        try:
            subprocess.run([*args, "sset", self.config.mixer_control, f"{volume}%"], check=False, **_QUIET)
            log.info("Output volume set to %d%% on '%s'.", volume, self.config.mixer_control)
        except FileNotFoundError:
            log.warning("amixer not found — leaving the system volume alone.")
        except Exception as exc:
            log.warning("Could not set output volume: %s", exc)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def play_startup(self) -> None:
        """Play the configured startup sound."""
        self.play_effect(self.config.startup_sound)

    def play_blink(self) -> None:
        """Play the configured blink sound."""
        self.play_effect(self.config.blink_sound)

    def play_effect(self, file_path: str) -> None:
        """Play a short sound effect in the background (.wav or .mp3)."""
        if not self.config.enabled or not file_path:
            return

        if not os.path.exists(file_path):
            log.warning("Audio file not found: %s", file_path)
            return

        extension = os.path.splitext(file_path)[1].lower()
        if extension == ".wav":
            command = ["aplay", "-D", self.config.device, file_path]
        elif extension == ".mp3":
            command = ["mpg123", "-q", "-a", self.config.device, file_path]
        else:
            log.warning("Unsupported audio format: %s", extension)
            return

        try:
            log.debug("Playing sound: %s", file_path)
            subprocess.Popen(command, **_QUIET)
        except FileNotFoundError:
            log.warning("No player installed for %s files.", extension)
        except Exception as exc:
            log.error("Failed to play sound %s: %s", file_path, exc)

    def play_speech(self, wav_bytes: bytes) -> None:
        """
        Play synthesized speech, blocking until it finishes.

        Blocking is deliberate: the caller mutes the microphone for exactly as
        long as this takes, so Eva does not transcribe her own voice.
        """
        if not self.config.enabled or not wav_bytes:
            return

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="eva_speech_", suffix=".wav", delete=False) as handle:
                handle.write(wav_bytes)
                temp_path = handle.name
        except Exception as exc:
            log.error("Could not write speech audio: %s", exc)
            return

        try:
            subprocess.run(["aplay", "-D", self.config.device, temp_path], check=False, **_QUIET)
        except FileNotFoundError:
            log.warning("aplay not found — cannot play speech.")
        except Exception as exc:
            log.error("Failed to play speech: %s", exc)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
