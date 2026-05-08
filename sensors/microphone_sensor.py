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
from typing import Optional

from config import MicrophoneConfig
from core.event_bus import Event, EventBus
from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger(__name__)


class MicrophoneSensor(BaseSensor):
    """
    Captures audio from the microphone in configurable-duration chunks.

    Each captured chunk is published as a "sensor.audio" event.
    Downstream: SpeechClient subscribes and sends chunks to the STT API.

    Strategy:
      - Capture audio in non-overlapping chunks of fixed duration.
      - TODO: Optionally apply VAD to only emit chunks containing speech.

    Attributes:
        name:   "microphone"
        config: MicrophoneConfig instance.
        _task:  Background asyncio task.
    """

    name = "microphone"

    def __init__(self, event_bus: EventBus, config: MicrophoneConfig) -> None:
        """
        Args:
            event_bus: Shared EventBus instance.
            config:    Microphone configuration.
        """
        super().__init__(event_bus)
        self.config = config
        self._task: Optional[asyncio.Task] = None
        self._audio_stream = None  # TODO: audio backend stream handle

    async def start(self) -> None:
        """
        Open the audio stream and start the background recording loop.

        TODO: Initialize audio backend (e.g. pyaudio.PyAudio(), open stream).
        """
        log.info("Starting microphone sensor.")
        self._running = True

        # TODO: Initialize audio stream.
        #   Example (PyAudio):
        #     pa = pyaudio.PyAudio()
        #     self._audio_stream = pa.open(
        #         format=pyaudio.paInt16,
        #         channels=self.config.channels,
        #         rate=self.config.sample_rate,
        #         input=True,
        #         input_device_index=self.config.device_index,
        #     )

        self._task = asyncio.create_task(self._record_loop(), name="microphone_record")
        log.info("Microphone sensor started.")

    async def stop(self) -> None:
        """
        Stop the recording loop and close the audio stream.
        """
        log.info("Stopping microphone sensor.")
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # TODO: Close audio stream.
        #   Example: if self._audio_stream: self._audio_stream.close()

        log.info("Microphone sensor stopped.")

    async def _record_loop(self) -> None:
        """
        Background loop: record an audio chunk, publish it, repeat.
        """
        while self._running:
            try:
                chunk = await self._record_chunk()
                if chunk is not None:
                    await self.event_bus.publish(
                        Event(topic="sensor.audio", data=chunk, source=self.name)
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Error during audio capture: %s", exc)

    async def _record_chunk(self) -> Optional[bytes]:
        """
        Record a single audio chunk of configured duration.

        Returns:
            Raw PCM bytes, or None if recording is not available.

        TODO: Implement actual audio recording, run in executor:
            loop = asyncio.get_event_loop()
            chunk = await loop.run_in_executor(None, self._read_chunk_sync)
            return chunk
        """
        # TODO: implement
        log.debug("Microphone chunk capture not yet implemented — sleeping.")
        await asyncio.sleep(self.config.chunk_duration_seconds)
        return None

    def _read_chunk_sync(self) -> Optional[bytes]:
        """
        Synchronous audio read (for use in run_in_executor).

        Returns:
            PCM audio bytes for one chunk.

        TODO: Implement audio read, e.g.:
            num_frames = int(self.config.sample_rate * self.config.chunk_duration_seconds)
            data = self._audio_stream.read(num_frames, exception_on_overflow=False)
            return data
        """
        # TODO: implement
        return None
