"""
sensors/camera_sensor.py — Monochrome camera frame capture.

Periodically captures frames from the monochrome camera and publishes
them as "sensor.vision" events on the EventBus.

The capture interval is configurable via CameraConfig.capture_interval_seconds.

Published events:
    topic:  "sensor.vision"
    data:   Raw image bytes (format TBD — e.g. JPEG, PNG, or numpy array).
    source: "camera"

TODO: Integrate with OpenCV (cv2) or picamera2 for actual frame capture.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config import CameraConfig
from core.event_bus import Event, EventBus
from sensors.base_sensor import BaseSensor
from utils.logger import get_logger

log = get_logger(__name__)


class CameraSensor(BaseSensor):
    """
    Captures frames from the monochrome camera at a fixed interval.

    Each captured frame is published as a "sensor.vision" event.
    Downstream: VisionClient subscribes and sends frames to the vision API.

    Attributes:
        name:     "camera"
        config:   CameraConfig instance.
        _task:    Background asyncio task for the capture loop.
    """

    name = "camera"

    def __init__(self, event_bus: EventBus, config: CameraConfig) -> None:
        """
        Args:
            event_bus: Shared EventBus instance.
            config:    Camera configuration.
        """
        super().__init__(event_bus)
        self.config = config
        self._task: Optional[asyncio.Task] = None
        self._capture_device = None  # TODO: initialize camera device here

    async def start(self) -> None:
        """
        Open the camera device and start the periodic frame capture loop.

        TODO: Initialize the camera hardware (e.g. cv2.VideoCapture).
        """
        log.info("Starting camera sensor (device %d).", self.config.device_index)
        self._running = True

        # TODO: Initialize camera hardware.
        #   Example: self._capture_device = cv2.VideoCapture(self.config.device_index)
        #   Check: if not self._capture_device.isOpened(): raise RuntimeError(...)

        self._task = asyncio.create_task(self._capture_loop(), name="camera_capture")
        log.info("Camera sensor started.")

    async def stop(self) -> None:
        """
        Stop the capture loop and release the camera device.
        """
        log.info("Stopping camera sensor.")
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # TODO: Release camera hardware.
        #   Example: if self._capture_device: self._capture_device.release()

        log.info("Camera sensor stopped.")

    async def _capture_loop(self) -> None:
        """
        Background loop: capture a frame, publish it, sleep, repeat.

        Runs until self._running is False or the task is cancelled.
        """
        while self._running:
            try:
                frame = await self._capture_frame()
                if frame is not None:
                    await self.event_bus.publish(
                        Event(topic="sensor.vision", data=frame, source=self.name)
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Error during camera capture: %s", exc)

            await asyncio.sleep(self.config.capture_interval_seconds)

    async def _capture_frame(self):
        """
        Capture a single frame from the camera.

        Returns:
            Raw frame data (bytes or numpy array), or None on failure.

        TODO: Implement actual capture using OpenCV or picamera2.
              Run the blocking camera read in an executor:
              loop = asyncio.get_event_loop()
              frame = await loop.run_in_executor(None, self._read_frame_sync)
        """
        # TODO: implement
        log.debug("Camera frame capture not yet implemented — returning None.")
        return None

    def _read_frame_sync(self):
        """
        Synchronous frame read (for use in run_in_executor).

        TODO: Implement camera read, e.g.:
            ret, frame = self._capture_device.read()
            if not ret: return None
            return frame
        """
        # TODO: implement
        return None
