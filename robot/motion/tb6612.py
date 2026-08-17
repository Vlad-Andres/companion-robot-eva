"""
motion/tb6612.py — The TB6612FNG dual H-bridge.

One chip, two motors. Each motor takes three signals: a PWM pin that sets how
hard it is driven, and two direction pins whose combination selects forward,
reverse, brake or coast. A shared standby pin has to be high or the chip
ignores everything — which is the first thing to check when nothing moves.

    IN1  IN2   what the motor does
    ---  ---   -------------------
     1    0    forward
     0    1    reverse
     1    1    short brake — stops hard, holds position
     0    0    coast — freewheels

Stopping uses brake rather than coast. A coasting robot keeps rolling for a
surprising distance on a smooth floor, and "stop" should mean stop.

Pins are in robot/config.py and default to GPIOs the WM8960 audio HAT does not
claim. Wiring is in robot/HARDWARE.md.
"""

from __future__ import annotations

from utils.logger import get_logger

from motion.base_driver import BaseDriver, clamp_speed

log = get_logger(__name__)


class _Motor:
    """One side of the H-bridge."""

    def __init__(self, pwm_pin: int, in1_pin: int, in2_pin: int, pwm_frequency: int) -> None:
        from gpiozero import DigitalOutputDevice, PWMOutputDevice

        self._pwm = PWMOutputDevice(pwm_pin, frequency=pwm_frequency, initial_value=0.0)
        self._in1 = DigitalOutputDevice(in1_pin, initial_value=False)
        self._in2 = DigitalOutputDevice(in2_pin, initial_value=False)

    def drive(self, speed: float) -> None:
        speed = clamp_speed(speed)
        if speed > 0:
            self._in1.on()
            self._in2.off()
        elif speed < 0:
            self._in1.off()
            self._in2.on()
        else:
            self.brake()
            return
        self._pwm.value = abs(speed)

    def brake(self) -> None:
        # Both direction pins high shorts the motor terminals, which stops it
        # far more decisively than cutting PWM and letting it freewheel.
        self._in1.on()
        self._in2.on()
        self._pwm.value = 0.0

    def close(self) -> None:
        self._pwm.close()
        self._in1.close()
        self._in2.close()


class TB6612BaseDriver(BaseDriver):
    """
    A two-wheel differential base on a TB6612FNG.

    Constructing this touches GPIO, so it raises on a machine without it —
    build_base_driver() catches that and falls back to the null driver.
    """

    def __init__(self, config) -> None:
        from gpiozero import DigitalOutputDevice

        self._config = config
        self._left = _Motor(config.left_pwm_pin, config.left_in1_pin, config.left_in2_pin, config.pwm_frequency_hz)
        self._right = _Motor(config.right_pwm_pin, config.right_in1_pin, config.right_in2_pin, config.pwm_frequency_hz)
        self._standby = DigitalOutputDevice(config.standby_pin, initial_value=True)

    def drive(self, left: float, right: float) -> None:
        left = clamp_speed(left) * self._sign(self._config.invert_left)
        right = clamp_speed(right) * self._sign(self._config.invert_right)
        self._standby.on()
        self._left.drive(left)
        self._right.drive(right)

    def stop(self) -> None:
        self._left.brake()
        self._right.brake()

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self._left.close()
            self._right.close()
            self._standby.close()

    @staticmethod
    def _sign(inverted: bool) -> float:
        """
        Which way round a motor is wired is a property of the wiring.

        Getting one backwards makes the robot spin when told to go forward,
        and the fix belongs in config rather than in swapped wires.
        """
        return -1.0 if inverted else 1.0
