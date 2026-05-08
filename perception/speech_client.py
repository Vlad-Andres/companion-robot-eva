"""
perception/speech_client.py — Voice-to-text API client.

Subscribes to "sensor.audio" events.
Sends audio chunks to the voice-to-text API.
Parses transcribed text.
Updates ContextManager and publishes "perception.speech" events.

Published events:
    topic:  "perception.speech"
    data:   str — transcribed text
    source: "speech_client"
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config import SpeechAPIConfig
from core.context_manager import ContextManager
from core.event_bus import Event, EventBus
from perception.base_perception import BasePerceptionClient
from utils.logger import get_logger
from utils.retry import async_retry

log = get_logger(__name__)


class SpeechClient(BasePerceptionClient):
    """
    Connects to the voice-to-text API and processes microphone audio events.

    Flow:
        1. Receives "sensor.audio" event (raw audio chunk).
        2. POSTs audio bytes to SpeechAPIConfig.base_url + endpoint.
        3. Parses "text" field from JSON response.
        4. Skips empty transcriptions.
        5. Updates ContextManager.last_speech and conversation history.
        6. Publishes "perception.speech" event.

    API contract expected response:
        {"text": "Hello robot, can you see my cup?"}
    """

    name = "speech_client"

    def __init__(
        self,
        event_bus: EventBus,
        context_manager: ContextManager,
        config: SpeechAPIConfig,
    ) -> None:
        """
        Args:
            event_bus:       Shared EventBus.
            context_manager: Shared ContextManager.
            config:          SpeechAPI configuration.
        """
        super().__init__(event_bus, context_manager)
        self.config = config
        self._semaphore = asyncio.Semaphore(1)

    async def start(self) -> None:
        """Subscribe to sensor.audio events."""
        if self.config.enabled:
            self.event_bus.subscribe("sensor.audio", self.process)
            log.info("SpeechClient subscribed to 'sensor.audio'.")
        else:
            log.info("SpeechClient disabled — skipping subscription.")

    async def stop(self) -> None:
        """Unsubscribe from sensor events."""
        self.event_bus.unsubscribe("sensor.audio", self.process)
        log.info("SpeechClient stopped.")

    async def process(self, event: Event) -> None:
        """
        Handle a sensor.audio event.

        Args:
            event: Event with raw audio chunk as data (bytes).
        """
        async with self._semaphore:
            audio_chunk = event.data
            if audio_chunk is None:
                return

            try:
                text = await async_retry(
                    self._call_api,
                    audio_chunk,
                    retries=2,
                    base_delay=0.3,
                )
            except Exception as exc:
                log.error("Speech API call failed: %s", exc)
                return

            if not text or not text.strip():
                log.debug("Empty transcription — skipping.")
                return

            log.info("Transcribed speech: %r", text)
            self.context.update_speech(text)
            await self.event_bus.publish(
                Event(
                    topic="perception.speech",
                    data=text,
                    source=self.name,
                )
            )

    async def _call_api(self, audio_chunk: bytes) -> Optional[str]:
        """
        Send the audio chunk to the voice-to-text API and return the transcript.

        Args:
            audio_chunk: Raw PCM audio bytes.

        Returns:
            Transcribed text string, or None/empty string if nothing was spoken.

        TODO: Implement actual HTTP POST using aiohttp or httpx.
              Example:
                  async with aiohttp.ClientSession() as session:
                      async with session.post(
                          url, data=audio_chunk,
                          headers={"Content-Type": "audio/pcm"},
                          timeout=self.config.timeout_seconds,
                      ) as resp:
                          data = await resp.json()
                          return data.get("text", "")
        """
        # TODO: implement
        log.debug("Speech API call not yet implemented — returning empty.")
        return ""
