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
    channels: int = 1
    # 512 samples = 32 ms, the frame size Silero VAD is built around. The
    # server reassembles these, so this is a transport size and has no effect
    # on transcription accuracy — Whisper only ever sees whole utterances.
    frame_samples: int = 512


@dataclass
class SpeechAPIConfig:
    """Configuration for the speech WebSocket session on the server."""
    base_url: str = "http://192.168.2.6:8002"  # Your Mac's LAN IP — check with: ipconfig getifaddr en0
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


@dataclass(frozen=True)
class Sound:
    """
    A sound effect, and how loud it is relative to the master volume.

    gain_percent is a trim, not an absolute level: 100 plays at the master
    volume untouched, 30 plays noticeably quieter than everything else.
    Anything below 100 rescales the samples, which costs a little quality —
    fine for short effects, which is why speech defaults to 100.
    """
    path: str
    gain_percent: int = 100


@dataclass
class AudioConfig:
    """Configuration for all speaker output — see utils/audio.AudioOutput."""
    enabled: bool = True
    device: str = "default"                 # ALSA device name (e.g. "hw:0,0" or "plughw:0,0")
    mixer_card: int | None = None
    mixer_control: str = "Master"

    # Master level, set once on the mixer at startup. This is the one knob
    # that moves everything; the per-sound gains below are relative to it.
    volume_percent: int = 70

    # Eva's voice. Leave at 100 so synthesized speech keeps its full dynamic
    # range; lower the master volume instead if she is too loud overall.
    speech_gain_percent: int = 100

    startup: Sound = field(default_factory=lambda: Sound("sounds/startup.mp3"))
    # Blinks fire every few seconds, so they sit well below the voice.
    blink: Sound = field(default_factory=lambda: Sound("sounds/blink3.wav", gain_percent=30))


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
