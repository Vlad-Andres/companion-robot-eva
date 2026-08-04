"""
The microphone has to keep up with real time.

It once did not, and the failure was quiet: audio still flowed, transcripts
still appeared, nothing errored — they were just further and further behind,
because the reassembly worker emitted one frame per device callback while the
device delivered four frames' worth. Capture ran at a quarter speed and the
backlog grew about three seconds for every second of speech.

Nothing about that is visible from a log line, so it is pinned here.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from config import MicrophoneConfig
from core.event_bus import EventBus
from sensors.microphone_sensor import MicrophoneSensor

SAMPLE_RATE = 16000
DEVICE_BUFFER = 2048   # pyaudio frames_per_buffer, several frames' worth


async def _capture(seconds: float, config: MicrophoneConfig) -> tuple[int, int, float]:
    """Feed callbacks at true device rate; return (fed, emitted, elapsed)."""
    bus = EventBus()
    emitted: list[bytes] = []

    async def on_audio(event) -> None:
        emitted.append(event.data)

    bus.subscribe("sensor.audio", on_audio)

    mic = MicrophoneSensor(bus, config)
    mic._loop = asyncio.get_running_loop()
    mic._running = True
    worker = threading.Thread(target=mic._reassembly_worker, daemon=True)
    worker.start()

    callback_bytes = DEVICE_BUFFER * 2 * config.channels
    interval = DEVICE_BUFFER / SAMPLE_RATE
    callbacks = int(seconds / interval)

    started = time.monotonic()
    for _ in range(callbacks):
        mic._raw_queue.put_nowait(b"\x11\x22" * (callback_bytes // 2))
        await asyncio.sleep(interval)
    await asyncio.sleep(0.25)
    elapsed = time.monotonic() - started

    mic._running = False
    worker.join(timeout=1.0)

    return callbacks * DEVICE_BUFFER, sum(len(c) // 2 for c in emitted), elapsed


@pytest.mark.asyncio
async def test_capture_keeps_up_with_real_time() -> None:
    """
    Every sample handed over by the device must come out the other side.

    Dropping any of it means the robot falls behind, and the delay compounds
    for as long as you keep talking.
    """
    fed, emitted, _ = await _capture(2.0, MicrophoneConfig())
    assert emitted >= fed * 0.98, (
        f"captured only {emitted / fed:.0%} of the audio — "
        "the worker is emitting fewer frames than the device delivers"
    )


@pytest.mark.asyncio
async def test_frame_rate_matches_the_sample_rate() -> None:
    """~31 frames a second at 512 samples each. Well under that means a backlog."""
    config = MicrophoneConfig()
    fed, emitted, elapsed = await _capture(2.0, config)

    expected = SAMPLE_RATE / config.frame_samples
    actual = (emitted / config.frame_samples) / elapsed
    assert actual > expected * 0.85, f"{actual:.1f} fps, expected about {expected:.1f}"


@pytest.mark.asyncio
async def test_a_device_that_falls_back_to_stereo_still_keeps_up() -> None:
    """The WM8960 sometimes rejects mono; downmixing must not cost samples."""
    config = MicrophoneConfig()
    config.channels = 2

    fed, emitted, _ = await _capture(2.0, config)
    # Stereo in, mono out: half the samples, all of the audio.
    assert emitted >= (fed / 2) * 0.98


def test_frames_are_the_size_the_detector_needs() -> None:
    """
    512 samples is not arbitrary — it is the only frame Silero accepts.

    Changing it here silently changes what the server has to reassemble.
    """
    assert MicrophoneConfig().frame_samples == 512
