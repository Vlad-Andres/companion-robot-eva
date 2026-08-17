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
