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
class BaseConfig:
    """
    The two-wheeled base, on a TB6612FNG dual H-bridge.

    Pins are BCM numbers and deliberately avoid everything the WM8960 audio
    HAT claims (GPIO 2, 3, 17, 18, 19, 20, 21) and the UART the range sensor
    uses (14, 15). GPIO 12 and 13 are the Pi's hardware PWM channels, which
    give steadier motor speed than a software-timed pulse. See HARDWARE.md.

    Set enabled = False on a robot with no motors wired; every layer above
    keeps working and movement is logged instead of driven.
    """
    enabled: bool = True

    left_pwm_pin: int = 12      # PWMA
    left_in1_pin: int = 5       # AIN1
    left_in2_pin: int = 6       # AIN2
    right_pwm_pin: int = 13     # PWMB
    right_in1_pin: int = 23     # BIN1
    right_in2_pin: int = 24     # BIN2
    standby_pin: int = 25       # STBY — low and the chip ignores everything

    pwm_frequency_hz: int = 1000

    # A motor wired the other way round makes "forward" spin the robot. The
    # fix belongs here rather than in swapped wires.
    invert_left: bool = False
    invert_right: bool = False

    # Fractions of full power. Low enough that a first run across a wooden
    # floor does not end at the skirting board.
    drive_speed: float = 0.55
    # Pivot turns fight more friction than driving straight, so a turn that
    # feels the same speed needs a little more power.
    turn_speed: float = 0.60


@dataclass
class RangeSensorConfig:
    """
    Forward-facing distance sensor — a US-100 in UART mode.

    Optional: an absent or unreadable sensor disables the obstacle reflex and
    is reported in the log, rather than stopping the robot from moving at all.
    Enabling the UART needs `sudo raspi-config nonint do_serial_hw 0` and the
    login console turned off — see HARDWARE.md.
    """
    enabled: bool = True
    port: str = "/dev/serial0"
    baud_rate: int = 9600
    poll_interval_seconds: float = 0.1

    # Refuse to drive forward closer than this.
    stop_distance_mm: int = 250
    # And do not consider the way clear again until there is this much room.
    # The gap between the two is what stops a sensor sitting on the threshold
    # from starting and stopping the motors several times a second.
    clear_distance_mm: int = 350
    # The US-100 tops out around 4.5 m; anything beyond is a bad reading.
    max_valid_mm: int = 4500


@dataclass
class EmergencyStopConfig:
    """
    A physical stop, on the button the WM8960 HAT already has.

    Voice cannot reach Eva while she is speaking — the microphone is muted so
    she does not transcribe herself — so for those few seconds a spoken "stop"
    has nowhere to land. A button always does.
    """
    enabled: bool = True
    button_pin: int = 17    # the HAT's onboard button


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
    base: BaseConfig = field(default_factory=BaseConfig)
    range_sensor: RangeSensorConfig = field(default_factory=RangeSensorConfig)
    emergency_stop: EmergencyStopConfig = field(default_factory=EmergencyStopConfig)
