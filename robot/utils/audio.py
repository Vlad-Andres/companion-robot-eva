"""
utils/audio.py — Simple audio playback utility using aplay.
"""

import subprocess
import os
import tempfile
from utils.logger import get_logger
from utils.wav_volume import apply_wav_volume

log = get_logger(__name__)


def set_alsa_volume(
    volume_percent: int,
    control: str = "Master",
    mixer_card: int | None = None,
    mixer_device: str = "default",
) -> None:
    try:
        vol = int(volume_percent)
    except Exception:
        return

    vol = max(0, min(100, vol))
    if not control:
        return

    args: list[str] = ["amixer", "-q"]
    if mixer_card is not None:
        args += ["-c", str(mixer_card)]
    else:
        args += ["-D", (mixer_device or "default")]

    try:
        subprocess.run(
            [*args, "sset", control, f"{vol}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return
    except Exception as exc:
        log.debug("Failed to set ALSA volume: %s", exc)


def play_sound(
    file_path: str,
    device: str = "default",
    volume_percent: int | None = None,
    mixer_control: str = "Master",
    mixer_card: int | None = None,
) -> None:
    """
    Play a sound file (.wav or .mp3).
    
    Uses 'aplay' for WAV and 'mpg123' for MP3.
    This is non-blocking (runs in the background).
    
    Args:
        file_path: Path to the audio file.
        device:    ALSA device name (default: "default").
    """
    if not file_path:
        return

    if not os.path.exists(file_path):
        log.warning("Audio file not found: %s", file_path)
        return

    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".wav":
        cmd = ["aplay", "-D", device, file_path]
    elif ext == ".mp3":
        # mpg123 uses -a for audio device
        cmd = ["mpg123", "-q", "-a", device, file_path]
    else:
        log.warning("Unsupported audio format: %s", ext)
        return

    try:
        if volume_percent is not None:
            set_alsa_volume(
                volume_percent,
                control=mixer_control,
                mixer_card=mixer_card,
                mixer_device=device,
            )
        # Run the command in the background
        log.debug("Playing sound: %s", file_path)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as exc:
        log.error("Failed to play sound %s: %s", file_path, exc)


def play_wav_bytes(
    wav_bytes: bytes,
    device: str = "default",
    volume_percent: int | None = None,
    mixer_control: str = "Master",
    mixer_card: int | None = None,
) -> None:
    if not wav_bytes:
        return

    if volume_percent is not None:
        wav_bytes = apply_wav_volume(wav_bytes, volume_percent)

    try:
        with tempfile.NamedTemporaryFile(prefix="robot_tts_", suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
    except Exception as exc:
        log.error("Failed to write wav bytes: %s", exc)
        return

    try:
        if volume_percent is not None:
            set_alsa_volume(
                volume_percent,
                control=mixer_control,
                mixer_card=mixer_card,
                mixer_device=device,
            )
        subprocess.Popen(
            ["aplay", "-D", device, tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.error("Failed to play wav bytes: %s", exc)


def play_wav_bytes_blocking(
    wav_bytes: bytes,
    device: str = "default",
    volume_percent: int | None = None,
    mixer_control: str = "Master",
    mixer_card: int | None = None,
) -> None:
    if not wav_bytes:
        return

    if volume_percent is not None:
        wav_bytes = apply_wav_volume(wav_bytes, volume_percent)

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="robot_tts_", suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
    except Exception as exc:
        log.error("Failed to write wav bytes: %s", exc)
        return

    try:
        if volume_percent is not None:
            set_alsa_volume(
                volume_percent,
                control=mixer_control,
                mixer_card=mixer_card,
                mixer_device=device,
            )
        subprocess.run(
            ["aplay", "-D", device, tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception as exc:
        log.error("Failed to play wav bytes: %s", exc)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
