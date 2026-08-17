"""
motion/base_driver.py — Turning wheel speeds into motor signals.

The layer above this one thinks in commands: forward, turn_left, stop. This
layer thinks in two numbers, one per wheel, each between -1 and 1. Everything
hardware-specific lives below the seam, which is what lets the whole movement
path be tested on a laptop and what makes swapping the motor driver a change
to one file.

`build_base_driver()` never raises. A Pi with no motor driver wired, or a
development machine with no GPIO at all, gets a NullBaseDriver that logs what
it would have done — the same shape of degradation as a missing display, and
for the same reason: one absent component should cost one capability, not the
whole robot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from utils.logger import get_logger

log = get_logger(__name__)


def clamp_speed(value: float) -> float:
    """Wheel speeds are a fraction of full power, signed for direction."""
    return max(-1.0, min(1.0, float(value)))


class BaseDriver(ABC):
    """A two-wheeled differential base."""

    #: Whether this driver actually reaches hardware. False for the null driver,
    #: which is what the capability manifest reports on.
    available: bool = True

    @abstractmethod
    def drive(self, left: float, right: float) -> None:
        """
        Set each wheel's speed, from -1 (full reverse) to 1 (full forward).

        Equal speeds drive straight; opposite speeds pivot on the spot, which
        is the turn a round chassis with two wheels and a castor can make.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Cut power to both wheels. Must be safe to call repeatedly."""
        ...

    def close(self) -> None:
        """Release the hardware. Stops first — always."""
        self.stop()


class NullBaseDriver(BaseDriver):
    """
    No motors. Logs what it would have done.

    Used on a development machine, and on a Pi whose base is not wired yet, so
    the whole path above — the server handshake, the command routing, the
    obstacle reflex — can be exercised before a single wire is connected.
    """

    available = False

    def __init__(self, reason: str = "no motor driver configured") -> None:
        self._reason = reason
        log.info("Base driver unavailable (%s) — movement will be logged, not driven.", reason)

    def drive(self, left: float, right: float) -> None:
        log.info("Base (simulated): left=%.2f right=%.2f", clamp_speed(left), clamp_speed(right))

    def stop(self) -> None:
        log.info("Base (simulated): stop")


def build_base_driver(config) -> BaseDriver:
    """
    Construct the configured driver, degrading to NullBaseDriver on any failure.

    Args:
        config: a BaseConfig — see robot/config.py.
    """
    if not config.enabled:
        return NullBaseDriver("disabled in config")

    try:
        from motion.tb6612 import TB6612BaseDriver

        driver = TB6612BaseDriver(config)
        log.info("TB6612 base driver initialised.")
        return driver
    except Exception as exc:
        # A missing gpiozero, an unavailable pin, no GPIO at all — all of them
        # mean the same thing to everything above: this robot cannot move.
        return NullBaseDriver(f"{type(exc).__name__}: {exc}")
