"""
perception/vision_client.py — Object recognition API client.

Subscribes to "sensor.vision" events.
Sends each camera frame to the object recognition API.
Parses the structured response into DetectedObject instances.
Updates ContextManager and publishes "perception.objects" events.

Published events:
    topic:  "perception.objects"
    data:   List[DetectedObject]
    source: "vision_client"
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from config import VisionAPIConfig
from core.context_manager import ContextManager, DetectedObject
from core.event_bus import Event, EventBus
from perception.base_perception import BasePerceptionClient
from utils.http_client import join_url, post_bytes_for_json
from utils.logger import get_logger
from utils.retry import async_retry

log = get_logger(__name__)


class VisionClient(BasePerceptionClient):
    """
    Connects to the object recognition API and processes vision sensor events.

    Flow:
        1. Receives "sensor.vision" event (raw camera frame).
        2. Encodes frame for HTTP transmission (TODO).
        3. POSTs to VisionAPIConfig.base_url + endpoint.
        4. Parses JSON response into List[DetectedObject].
        5. Updates ContextManager.current_objects.
        6. Publishes "perception.objects" event.

    API contract expected response:
        {
            "objects": [
                {
                    "label": "person",
                    "position": {"x": 120, "y": 84, "width": 60, "height": 150},
                    "confidence": 0.94
                }
            ]
        }
    """

    name = "vision_client"

    def __init__(
        self,
        event_bus: EventBus,
        context_manager: ContextManager,
        config: VisionAPIConfig,
    ) -> None:
        """
        Args:
            event_bus:       Shared EventBus.
            context_manager: Shared ContextManager.
            config:          VisionAPI configuration.
        """
        super().__init__(event_bus, context_manager)
        self.config = config
        self._semaphore = asyncio.Semaphore(1)  # One API call at a time

    async def start(self) -> None:
        """Subscribe to sensor.vision events."""
        if self.config.enabled:
            self.event_bus.subscribe("sensor.vision", self.process)
            log.info("VisionClient subscribed to 'sensor.vision'.")
        else:
            log.info("VisionClient disabled — skipping subscription.")

    async def stop(self) -> None:
        """Unsubscribe from sensor events."""
        self.event_bus.unsubscribe("sensor.vision", self.process)
        log.info("VisionClient stopped.")

    async def process(self, event: Event) -> None:
        """
        Handle a sensor.vision event.

        Uses a semaphore to prevent concurrent API calls if frames arrive
        faster than the API responds.

        Args:
            event: Event with raw camera frame as data.
        """
        if not self._semaphore.locked():
            async with self._semaphore:
                frame = event.data
                if frame is None:
                    return

                try:
                    objects = await async_retry(
                        self._call_api,
                        frame,
                        retries=2,
                        base_delay=0.3,
                    )
                    self.context.update_objects(objects)
                    await self.event_bus.publish(
                        Event(
                            topic="perception.objects",
                            data=objects,
                            source=self.name,
                        )
                    )
                except Exception as exc:
                    log.error("Vision API call failed: %s", exc)
        else:
            log.debug("Vision API call in progress — dropping frame.")

    async def _call_api(self, frame) -> List[DetectedObject]:
        """
        Send the frame to the object recognition API and parse the response.

        Args:
            frame: Raw image data (bytes or numpy array).

        Returns:
            List of DetectedObject instances.

        """
        if isinstance(frame, bytes):
            payload = frame
            content_type = "application/octet-stream"
        else:
            raise TypeError("Vision frame must be bytes (JPEG/PNG recommended)")

        url = join_url(self.config.base_url, self.config.endpoint)
        data = await post_bytes_for_json(
            url=url,
            payload=payload,
            content_type=content_type,
            timeout_seconds=self.config.timeout_seconds,
        )
        return self._parse_response(data)

    def _parse_response(self, data: dict) -> List[DetectedObject]:
        """
        Parse the API JSON response into DetectedObject instances.

        Args:
            data: Parsed JSON dict from the API.

        Returns:
            List of DetectedObject instances.

        Raises:
            ValueError: If the response format is unexpected.
        """
        objects = []
        for item in data.get("objects", []):
            position = item.get("position", {})
            obj = DetectedObject(
                label=item["label"],
                x=position.get("x", 0),
                y=position.get("y", 0),
                width=position.get("width", 0),
                height=position.get("height", 0),
                confidence=item.get("confidence", 1.0),
            )
            objects.append(obj)
        return objects
