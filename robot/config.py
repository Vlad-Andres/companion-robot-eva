"""
config.py — Robot configuration.

All runtime parameters are collected here as dataclasses. Edit the defaults
directly; there is no config file layer yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------


@dataclass
class DisplayConfig:
    """Configuration for the OLED display / eye controller."""
    i2c_port: int = 1
    i2c_address: int = 0x3C
    width: int = 128
    height: int = 32


@dataclass
class MicrophoneConfig:
    """Configuration for audio capture."""
    device_index: Optional[int] = None
    sample_rate: int = 16000
    chunk_duration_seconds: float = 1.5      # 1.5s is the "sweet spot" for speed vs accuracy
    channels: int = 1


@dataclass
class SpeechAPIConfig:
    """Configuration for the speech WebSocket session on the server."""
    base_url: str = "http://192.168.1.4:8002"  # Your Mac's LAN IP — check with: ipconfig getifaddr en0
    endpoint: str = "/v1/websocket/audio"     # Must match the server's WebSocket route
    timeout_seconds: float = 30.0            # Increased to 30s for local speech-to-text
    enabled: bool = True


@dataclass
class IdleBlinkConfig:
    """Configuration for the autonomous idle blink behaviour."""
    enabled: bool = True
    min_interval_seconds: float = 3.0   # Minimum seconds between blinks
    max_interval_seconds: float = 8.0   # Maximum seconds between blinks
    long_blink_chance: float = 0.2      # Probability of a slow blink (vs quick)


@dataclass
class AudioConfig:
    """Configuration for sound effects."""
    enabled: bool = True
    device: str = "default"                 # ALSA device name (e.g. "hw:0,0" or "plughw:0,0")
    mixer_card: int | None = None
    mixer_control: str = "Master"
    volume_percent: int = 5
    startup_sound: str = "sounds/startup.mp3"
    blink_sound: str = "sounds/blink3.wav"


@dataclass
class RuntimeConfig:
    """Configuration for the main agent loop."""
    startup_animation: str = "WAKEUP"   # Eye animation on startup
    log_level: str = "INFO"


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


@dataclass
class RobotConfig:
    """
    Top-level configuration object.

    Usage:
        config = RobotConfig()   # all defaults
    """
    display: DisplayConfig = field(default_factory=DisplayConfig)
    microphone: MicrophoneConfig = field(default_factory=MicrophoneConfig)
    speech_api: SpeechAPIConfig = field(default_factory=SpeechAPIConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    idle_blink: IdleBlinkConfig = field(default_factory=IdleBlinkConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
