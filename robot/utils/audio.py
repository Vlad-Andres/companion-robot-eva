"""
utils/audio.py — Every sound the robot makes goes out through here.

One AudioOutput instance owns the audio settings and is injected wherever
sound is played, so the device, the volume and the on/off switch live in
exactly one place.

Two levels, and they do different jobs:

  * The master volume is the mixer's, applied once by apply_volume() at
    startup. It moves everything.
  * A Sound's gain_percent is a trim relative to that master, so a blink can
    sit below the voice. A trim below 100 rescales samples, which costs a
    little quality — so speech stays at 100 by default and you turn the
    master down instead.

Applying both to the same sound is what previously left output at 0.25% of
full scale, so the two are kept deliberately distinct: the mixer is set once
and never per-playback.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from config import AudioConfig, Sound
from utils.logger import get_logger
from utils.wav_volume import apply_wav_volume

log = get_logger(__name__)

_QUIET = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def _clamp_percent(value: int) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 100


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
        # Trimmed copies of effect files, made once and reused: blinks fire
        # every few seconds and rescaling the same WAV each time is waste.
        self._trimmed: dict[tuple[str, int], str] = {}

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

        volume = _clamp_percent(self.config.volume_percent)
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
        self.play_effect(self.config.startup)

    def play_blink(self) -> None:
        """Play the configured blink sound."""
        self.play_effect(self.config.blink)

    def play_effect(self, sound: Sound) -> None:
        """Play a short sound effect in the background (.wav or .mp3)."""
        if not self.config.enabled or not sound.path:
            return

        if not os.path.exists(sound.path):
            log.warning("Audio file not found: %s", sound.path)
            return

        gain = _clamp_percent(sound.gain_percent)
        extension = os.path.splitext(sound.path)[1].lower()

        if extension == ".wav":
            # aplay has no volume flag, so a trim means rescaling the samples.
            path = sound.path if gain == 100 else self._trimmed_wav(sound.path, gain)
            if path is None:
                return
            command = ["aplay", "-D", self.config.device, path]
        elif extension == ".mp3":
            # mpg123 scales in the decoder: 32768 is unity.
            command = ["mpg123", "-q", "-a", self.config.device]
            if gain != 100:
                command += ["-f", str(int(32768 * gain / 100))]
            command.append(sound.path)
        else:
            log.warning("Unsupported audio format: %s", extension)
            return

        try:
            log.debug("Playing sound: %s at %d%% of master", sound.path, gain)
            subprocess.Popen(command, **_QUIET)
        except FileNotFoundError:
            log.warning("No player installed for %s files.", extension)
        except Exception as exc:
            log.error("Failed to play sound %s: %s", sound.path, exc)

    def _trimmed_wav(self, path: str, gain: int) -> str | None:
        """Return a path to `path` rescaled to `gain`, building it once."""
        key = (path, gain)
        cached = self._trimmed.get(key)
        if cached and os.path.exists(cached):
            return cached

        try:
            with open(path, "rb") as handle:
                trimmed = apply_wav_volume(handle.read(), gain)
            with tempfile.NamedTemporaryFile(prefix="eva_effect_", suffix=".wav", delete=False) as out:
                out.write(trimmed)
                self._trimmed[key] = out.name
            return out.name
        except Exception as exc:
            log.warning("Could not apply gain to %s: %s — playing untrimmed.", path, exc)
            return path

    def play_speech(self, wav_bytes: bytes) -> None:
        """
        Play synthesized speech, blocking until it finishes.

        Blocking is deliberate: the caller mutes the microphone for exactly as
        long as this takes, so Eva does not transcribe her own voice.
        """
        if not self.config.enabled or not wav_bytes:
            return

        gain = _clamp_percent(self.config.speech_gain_percent)
        if gain != 100:
            wav_bytes = apply_wav_volume(wav_bytes, gain)

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
