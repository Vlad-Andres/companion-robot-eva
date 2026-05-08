"""
utils/audio.py — Simple audio playback utility using aplay.
"""

import subprocess
import os
import tempfile
from utils.logger import get_logger

log = get_logger(__name__)

def play_sound(file_path: str, device: str = "default") -> None:
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
        # Run the command in the background
        log.debug("Playing sound: %s", file_path)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as exc:
        log.error("Failed to play sound %s: %s", file_path, exc)


def play_wav_bytes(wav_bytes: bytes, device: str = "default") -> None:
    if not wav_bytes:
        return

    try:
        with tempfile.NamedTemporaryFile(prefix="robot_tts_", suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
    except Exception as exc:
        log.error("Failed to write wav bytes: %s", exc)
        return

    try:
        subprocess.Popen(
            ["aplay", "-D", device, tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.error("Failed to play wav bytes: %s", exc)
