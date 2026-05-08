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
import threading
import queue
from typing import Optional

from config import MicrophoneConfig
from core.event_bus import Event, EventBus
from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger(__name__)


class MicrophoneSensor(BaseSensor):
    """
    Captures audio from the microphone.
    Uses a dedicated background thread for chunk reassembly to prevent ALSA overflows.
    """

    name = "microphone"

    def __init__(self, event_bus: EventBus, config: MicrophoneConfig) -> None:
        super().__init__(event_bus)
        self.config = config
        self._pa: Optional[pyaudio.PyAudio] = None
        self._audio_stream: Optional[pyaudio.Stream] = None
        
        # Thread-safe communication
        self._raw_queue = queue.Queue(maxsize=100)
        self._worker_thread: Optional[threading.Thread] = None
        self._loop = None

    async def start(self) -> None:
        log.info("Starting microphone sensor (channels=%d, rate=%d).", 
                 self.config.channels, self.config.sample_rate)
        
        self._loop = asyncio.get_running_loop()
        
        try:
            self._pa = pyaudio.PyAudio()
            
            # Attempt to open the stream
            self._audio_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=self.config.device_index,
                frames_per_buffer=2048, # Moderate buffer for lower latency
                stream_callback=self._stream_callback
            )
        except Exception as exc:
            log.error("Failed to open audio stream: %s. Trying fallback to stereo...", exc)
            # Fallback for WM8960 if mono is rejected by driver
            try:
                self.config.channels = 2
                self._audio_stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=2,
                    rate=self.config.sample_rate,
                    input=True,
                    input_device_index=self.config.device_index,
                    frames_per_buffer=2048,
                    stream_callback=self._stream_callback
                )
                log.info("Successfully opened fallback stereo stream.")
            except Exception as exc2:
                log.error("Fatal audio error: %s", exc2)
                if self._pa: self._pa.terminate()
                return

        self._running = True
        
        # Start the background worker thread
        self._worker_thread = threading.Thread(target=self._reassembly_worker, daemon=True)
        self._worker_thread.start()
        
        log.info("Microphone sensor started.")

    def _stream_callback(self, in_data, frame_count, time_info, status):
        """Minimal callback to prevent blocking the audio interrupt."""
        if status & pyaudio.paInputOverflow:
            # We log this but it's less likely now with the queue
            pass 
        
        if in_data and self._running:
            try:
                self._raw_queue.put_nowait(in_data)
            except queue.Full:
                pass # Drop data if we're completely stuck
        
        return (None, pyaudio.paContinue)

    def _reassembly_worker(self):
        """Dedicated thread to process and reassemble audio chunks."""
        frames_per_chunk = int(self.config.sample_rate * self.config.chunk_duration_seconds)
        bytes_per_frame = 2 * self.config.channels
        target_bytes = frames_per_chunk * bytes_per_frame
        
        collected = bytearray()
        
        while self._running:
            try:
                # Block for 100ms waiting for data
                data = self._raw_queue.get(timeout=0.1)
                collected.extend(data)
                
                if len(collected) >= target_bytes:
                    chunk_raw = bytes(collected[:target_bytes])
                    del collected[:target_bytes]
                    
                    # Process (Mono conversion)
                    processed = self._process_raw_data(chunk_raw)
                    
                    # Send back to asyncio loop
                    if processed and self._loop:
                        asyncio.run_coroutine_threadsafe(
                            self.event_bus.publish(
                                Event(topic="sensor.audio", data=processed, source=self.name)
                            ),
                            self._loop
                        )
            except queue.Empty:
                continue
            except Exception as e:
                log.error("Error in audio reassembly worker: %s", e)

    async def stop(self) -> None:
        log.info("Stopping microphone sensor.")
        self._running = False
        
        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)

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

    def _process_raw_data(self, raw_data: bytes) -> Optional[bytes]:
        """Fast mono conversion using NumPy."""
        try:
            if self.config.channels == 2:
                # Faster conversion for Stereo -> Mono
                samples = np.frombuffer(raw_data, dtype=np.int16)
                # Take every 2nd sample and average with neighbor
                mono = (samples[0::2].astype(np.int32) + samples[1::2].astype(np.int32)) // 2
                return mono.astype(np.int16).tobytes()
            return raw_data
        except Exception as exc:
            log.error("Failed to process audio data: %s", exc)
            return None
