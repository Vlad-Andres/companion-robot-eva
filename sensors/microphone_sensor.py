"""
sensors/microphone_sensor.py — Audio chunk capture from the microphone.

Continuously captures audio chunks from the microphone and publishes them
as "sensor.audio" events on the EventBus.

Published events:
    topic:  "sensor.audio"
    data:   Raw audio bytes (PCM format, configurable rate/channels).
    source: "microphone"

TODO: Integrate with PyAudio, sounddevice, or similar for actual capture.
      Consider VAD (Voice Activity Detection) to only publish when speech detected.
"""

from __future__ import annotations

import asyncio
import numpy as np
import pyaudio
import collections
from typing import Optional

from config import MicrophoneConfig
from core.event_bus import Event, EventBus
from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger(__name__)


class MicrophoneSensor(BaseSensor):
    """
    Captures audio from the microphone in configurable-duration chunks.
    Uses a high-priority PyAudio callback and a deque for maximum stability.
    """

    name = "microphone"

    def __init__(self, event_bus: EventBus, config: MicrophoneConfig) -> None:
        super().__init__(event_bus)
        self.config = config
        self._task: Optional[asyncio.Task] = None
        self._pa: Optional[pyaudio.PyAudio] = None
        self._audio_stream: Optional[pyaudio.Stream] = None
        
        # Fast thread-safe buffer for callback
        self._buffer = collections.deque()

    async def start(self) -> None:
        log.info("Starting microphone sensor (channels=%d, rate=%d).", 
                 self.config.channels, self.config.sample_rate)
        
        try:
            self._pa = pyaudio.PyAudio()
            self._audio_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=self.config.device_index,
                frames_per_buffer=4096, # Increased for stability
                stream_callback=self._stream_callback
            )
        except Exception as exc:
            log.error("Failed to open audio stream: %s", exc)
            if self._pa:
                self._pa.terminate()
            return

        self._running = True
        self._task = asyncio.create_task(self._record_loop(), name="microphone_record")
        log.info("Microphone sensor started.")

    def _stream_callback(self, in_data, frame_count, time_info, status):
        """High-priority callback from PortAudio."""
        if status & pyaudio.paInputOverflow:
            log.warning("Audio Input Overflow (Status 2) — system too slow.")
        
        if in_data:
            self._buffer.append(in_data)
        
        return (None, pyaudio.paContinue)

    async def stop(self) -> None:
        log.info("Stopping microphone sensor.")
        self._running = False
        
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None

        if self._pa:
            self._pa.terminate()
            self._pa = None

        log.info("Microphone sensor stopped.")

    async def _record_loop(self) -> None:
        """Assembles chunks from the deque and publishes them."""
        frames_per_chunk = int(self.config.sample_rate * self.config.chunk_duration_seconds)
        bytes_per_sample = 2
        target_bytes = frames_per_chunk * self.config.channels * bytes_per_sample
        
        collected_data = bytearray()

        while self._running:
            try:
                # Pull all available data from the deque
                while self._buffer:
                    collected_data.extend(self._buffer.popleft())

                if len(collected_data) >= target_bytes:
                    # Extract the chunk
                    chunk_raw = bytes(collected_data[:target_bytes])
                    # Keep the remainder
                    del collected_data[:target_bytes]
                    
                    # Process and publish
                    processed = self._process_raw_data(chunk_raw)
                    if processed:
                        await self.event_bus.publish(
                            Event(topic="sensor.audio", data=processed, source=self.name)
                        )

                await asyncio.sleep(0.1) # Check buffer every 100ms

            except Exception as exc:
                log.error("Error in record loop: %s", exc)
                await asyncio.sleep(0.5)

    def _process_raw_data(self, raw_data: bytes) -> Optional[bytes]:
        try:
            if self.config.channels > 1:
                samples = np.frombuffer(raw_data, dtype=np.int16)
                samples = samples.reshape(-1, self.config.channels)
                mono_samples = samples.mean(axis=1).astype(np.int16)
                return mono_samples.tobytes()
            return raw_data
        except Exception as exc:
            log.error("Failed to process audio data: %s", exc)
            return None
