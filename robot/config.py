"""
config.py — Robot configuration.

All runtime parameters are collected here as dataclasses.
Load from a YAML file via RobotConfig.from_yaml(), or use defaults.
"""

from __future__ import annotations

import os
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
class CameraConfig:
    """Configuration for the monochrome camera sensor."""
    device_index: int = 0
    capture_interval_seconds: float = 2.0   # How often to capture a frame
    resolution: tuple[int, int] = (640, 480)


@dataclass
class MicrophoneConfig:
    """Configuration for audio capture."""
    device_index: Optional[int] = None
    sample_rate: int = 16000
    chunk_duration_seconds: float = 1.5      # 1.5s is the "sweet spot" for speed vs accuracy
    channels: int = 1


@dataclass
class VisionAPIConfig:
    """Configuration for the object recognition API."""
    base_url: str = "http://localhost:8001"
    endpoint: str = "/recognize"
    timeout_seconds: float = 5.0
    enabled: bool = True


@dataclass
class SpeechAPIConfig:
    """Configuration for the voice-to-text API."""
    base_url: str = "http://192.168.2.4:8002" # Updated to your computer's IP
    endpoint: str = "/transcribe"
    timeout_seconds: float = 30.0            # Increased to 30s for local STT
    enabled: bool = True


@dataclass
class DecisionAPIConfig:
    """Configuration for the decision LLM API."""
    base_url: str = "http://localhost:8003"
    endpoint: str = "/decide"
    timeout_seconds: float = 15.0
    max_history_turns: int = 10             # How many turns to include in context
    enabled: bool = True


@dataclass
class MemoryConfig:
    """Configuration for the memory store."""
    short_term_capacity: int = 50           # Max events in short-term ring buffer
    long_term_path: str = "memory.json"     # Path to persistent long-term store


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
    blink_sound: str = "sounds/blink.wav"


@dataclass
class RuntimeConfig:
    """Configuration for the main agent loop."""
    decision_loop_interval_seconds: float = 1.0   # Minimum time between LLM calls
    startup_animation: str = "WAKEUP"             # Eye animation on startup
    log_level: str = "INFO"


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


@dataclass
class RobotConfig:
    """
    Top-level configuration object.

    Usage:
        config = RobotConfig()               # all defaults
        config = RobotConfig.from_yaml(path) # from file
    """
    display: DisplayConfig = field(default_factory=DisplayConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    microphone: MicrophoneConfig = field(default_factory=MicrophoneConfig)
    vision_api: VisionAPIConfig = field(default_factory=VisionAPIConfig)
    speech_api: SpeechAPIConfig = field(default_factory=SpeechAPIConfig)
    decision_api: DecisionAPIConfig = field(default_factory=DecisionAPIConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    idle_blink: IdleBlinkConfig = field(default_factory=IdleBlinkConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "RobotConfig":
        """
        Load configuration from a YAML file.

        TODO: Implement YAML parsing and map to dataclass fields.
              Use PyYAML or similar. Merge with defaults for missing keys.
        """
        # TODO: implement
        raise NotImplementedError("YAML config loading not yet implemented.")

    @classmethod
    def from_env(cls) -> "RobotConfig":
        """
        Load configuration overrides from environment variables.

        Convention: ROBOT_<SECTION>_<KEY>=value
        e.g. ROBOT_DISPLAY_I2C_ADDRESS=0x3C

        TODO: Implement env variable parsing and override logic.
        """
        # TODO: implement
        raise NotImplementedError("Env config loading not yet implemented.")
