"""
Shared setup for the robot tests.

The robot imports hardware drivers at module scope, which are not installable
on a development machine. Stubbing them here lets the logic above the drivers
be tested anywhere — which is the part that has actually broken.
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_gpiozero_stub() -> None:
    """
    Fake pins that record what was asked of them.

    The point is not to simulate a TB6612 — it is that the layers above the
    driver, where the logic lives, can be tested without one. Each device
    keeps its last value so a test can assert on the signals a command
    produced.
    """
    if "gpiozero" in sys.modules:
        return

    gpiozero = types.ModuleType("gpiozero")

    class _Device:
        def __init__(self, pin, **kwargs):
            self.pin = pin
            self.value = kwargs.get("initial_value", 0)
            self.closed = False

        def on(self):
            self.value = 1

        def off(self):
            self.value = 0

        def close(self):
            self.closed = True

    class _PWMOutputDevice(_Device):
        def __init__(self, pin, frequency=100, initial_value=0.0):
            super().__init__(pin, initial_value=initial_value)
            self.frequency = frequency

    class _Button(_Device):
        def __init__(self, pin, pull_up=True, bounce_time=None):
            super().__init__(pin)
            self.when_pressed = None

    gpiozero.DigitalOutputDevice = _Device
    gpiozero.PWMOutputDevice = _PWMOutputDevice
    gpiozero.Button = _Button
    sys.modules["gpiozero"] = gpiozero


def _install_serial_stub() -> None:
    """No UART on a laptop. Opening a port raises, which is the absent case."""
    if "serial" in sys.modules:
        return

    serial = types.ModuleType("serial")

    class _Serial:
        def __init__(self, *_args, **_kwargs):
            raise OSError("no serial port in tests")

    serial.Serial = _Serial
    serial.SerialException = OSError
    sys.modules["serial"] = serial


def _install_pyaudio_stub() -> None:
    if "pyaudio" in sys.modules:
        return

    pyaudio = types.ModuleType("pyaudio")
    pyaudio.paInt16 = 8
    pyaudio.paContinue = 0
    pyaudio.paInputOverflow = 0

    class _PyAudio:
        def open(self, **_kwargs):
            raise RuntimeError("no audio device in tests")

        def terminate(self) -> None:
            return

    pyaudio.PyAudio = _PyAudio
    sys.modules["pyaudio"] = pyaudio


_install_pyaudio_stub()
_install_gpiozero_stub()
_install_serial_stub()
