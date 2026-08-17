"""
perception/speech_client.py — WebSocket client for the server session.

Subscribes to "sensor.audio" events and streams audio chunks to the server.
Routes server replies (transcripts, commands, speech, audio) onto the bus.

Published events (all with source "speech_client"):
    perception.transcript        — str, final transcript of what Eva heard
    perception.backend_command   — dict, one command envelope to execute
    perception.backend_speech    — str, reply text the server is about to speak
    perception.backend_audio     — bytes, synthesized WAV to play
    perception.backend_listening — None, the server detected speech
    perception.backend_waiting   — None, the server is thinking
    perception.backend_ready     — None, the turn is over
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import websockets

from config import SpeechAPIConfig
from core.event_bus import Event, EventBus
from perception.base_perception import BasePerceptionClient
from utils.logger import get_logger

log = get_logger(__name__)


class SpeechClient(BasePerceptionClient):
    """
    Connects to the voice-to-text API via WebSockets for low-latency streaming.
    """

    name = "speech_client"

    def __init__(
        self,
        event_bus: EventBus,
        config: SpeechAPIConfig,
        manifest: Optional[dict] = None,
    ) -> None:
        """
        Args:
            manifest: this robot's hardware, sent on connect. The server builds
                      the language model's output schema from it, so a robot
                      that declares no base is never asked to move. None sends
                      nothing, and the server assumes everything.
        """
        super().__init__(event_bus)
        self.config = config
        self._manifest = manifest
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._outbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._manager_task: Optional[asyncio.Task] = None
        self._send_allowed = asyncio.Event()
        self._send_allowed.set()

    async def start(self) -> None:
        """Subscribe to events and start the connection manager."""
        if self.config.enabled:
            self.event_bus.subscribe("sensor.audio", self.process)
            self.event_bus.subscribe("perception.backend_audio_playing", self._on_backend_audio_playing)
            self.event_bus.subscribe("perception.backend_audio_done", self._on_backend_audio_done)
            # The manager owns the full lifecycle of the connection
            self._manager_task = asyncio.create_task(self._connection_manager())
            log.info("SpeechClient started (Best-practice WebSocket mode).")
        else:
            log.info("SpeechClient disabled.")

    async def stop(self) -> None:
        """Unsubscribe and stop the manager."""
        self.event_bus.unsubscribe("sensor.audio", self.process)
        self.event_bus.unsubscribe("perception.backend_audio_playing", self._on_backend_audio_playing)
        self.event_bus.unsubscribe("perception.backend_audio_done", self._on_backend_audio_done)
        if self._manager_task:
            self._manager_task.cancel()
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
        log.info("SpeechClient stopped.")

    async def _connection_manager(self) -> None:
        """
        Main lifecycle task. Handles persistent connection, 
        sending (producer), and receiving (consumer).
        """
        websocket_url = self.config.base_url.replace("http://", "ws://").replace("https://", "wss://")
        websocket_url = websocket_url.rstrip("/") + self.config.endpoint

        while True:
            try:
                log.info("Connecting to speech WebSocket at %s...", websocket_url)
                async with websockets.connect(websocket_url) as websocket:
                    log.info("speech WebSocket connected.")
                    self._websocket = websocket
                    await self._announce_capabilities()

                    # Run producer (sender) and consumer (receiver) concurrently
                    # If either fails, both will be cancelled and we'll reconnect.
                    producer = asyncio.create_task(self._producer_loop())
                    consumer = asyncio.create_task(self._consumer_loop())

                    _done, pending = await asyncio.wait(
                        [producer, consumer],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cleanup
                    for task in pending:
                        task.cancel()

                log.warning("WebSocket connection closed normally. Reconnecting...")
            except asyncio.CancelledError:
                break
            except (websockets.ConnectionClosed, Exception) as e:
                log.error("WebSocket error: %s. Retrying in 5s...", e)

            self._websocket = None
            # Anything with wheels needs to hear about this: a movement the
            # server started can no longer be stopped by the server.
            await self.event_bus.publish(
                Event(topic="perception.backend_disconnected", data=None, source=self.name)
            )
            await asyncio.sleep(5)

    async def _announce_capabilities(self) -> None:
        """
        Tell the server what this robot has, before any audio.

        Sent on every connection, not just the first: a reconnect gets a fresh
        session on the server with no memory of the last one, and a session
        that never heard the manifest assumes the robot has everything.
        """
        if self._manifest is None or self._websocket is None:
            return
        try:
            await self._websocket.send(json.dumps(self._manifest))
            log.info(
                "Announced capabilities: sensors=%s actuators=%s",
                self._manifest.get("sensors"),
                self._manifest.get("actuators"),
            )
        except Exception as exc:
            log.warning("Could not announce capabilities: %s", exc)

    async def _producer_loop(self) -> None:
        """Pulls audio chunks from the outbox queue and sends them."""
        while True:
            await self._send_allowed.wait()
            chunk = await self._outbox.get()
            if self._websocket:
                try:
                    await self._websocket.send(chunk)
                except Exception as e:
                    log.error("Failed to send chunk: %s", e)
                    raise
            self._outbox.task_done()

    def _drain_outbox(self) -> None:
        while True:
            try:
                self._outbox.get_nowait()
                self._outbox.task_done()
            except asyncio.QueueEmpty:
                return

    async def _on_backend_audio_playing(self, _event: Event) -> None:
        self._send_allowed.clear()
        self._drain_outbox()

    async def _on_backend_audio_done(self, _event: Event) -> None:
        self._send_allowed.set()

    async def _consumer_loop(self) -> None:
        """Listens for transcription results from the server."""
        if not self._websocket:
            return
        async for message in self._websocket:
            try:
                if isinstance(message, (bytes, bytearray)):
                    await self.event_bus.publish(
                        Event(topic="perception.backend_audio", data=bytes(message), source=self.name)
                    )
                    continue

                text = str(message).strip()
                if not text:
                    continue

                await self._handle_envelope(text)
            except Exception as e:
                log.error("Error handling server message: %s", e)

    async def _handle_envelope(self, text: str) -> None:
        """
        Route one JSON message from the server.

        Message shapes are defined in server/protocol.py. Anything unrecognised
        is logged rather than spoken, so Eva never reads raw JSON aloud.
        """
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Ignoring malformed JSON from server: %.80s", text)
            return
        if not isinstance(message, dict):
            return

        message_type = message.get("type")

        if message_type == "command":
            command = message.get("command")
            if isinstance(command, dict):
                await self.event_bus.publish(
                    Event(topic="perception.backend_command", data=command, source=self.name)
                )
            return

        if message_type == "transcript.final":
            heard = str(message.get("text") or "").strip()
            if heard:
                log.info("Heard: %r", heard)
                await self.event_bus.publish(
                    Event(topic="perception.transcript", data=heard, source=self.name)
                )
            return

        if message_type == "speech.start":
            spoken = str(message.get("speech", {}).get("text") or "").strip()
            if spoken:
                await self.event_bus.publish(
                    Event(topic="perception.backend_speech", data=spoken, source=self.name)
                )
            return

        if message_type == "status":
            # Eva's expression follows the server's real state. The robot used
            # to infer "waiting" from having sent audio, which was fine while a
            # gate meant audio only moved when you spoke — but now that every
            # frame is streamed, that inference would leave her permanently
            # thinking.
            state = message.get("state")
            topic = {
                "listening": "perception.backend_listening",
                "thinking": "perception.backend_waiting",
                "ready": "perception.backend_ready",
            }.get(str(state or ""))
            if topic:
                await self.event_bus.publish(Event(topic=topic, data=None, source=self.name))
            return

        if message_type == "capabilities.ack":
            # The complementary half of the handshake: exactly which commands
            # this session can send. Anything else arriving is a server bug,
            # and logging this is what makes that visible during bring-up.
            actions = [a.get("name") for a in message.get("actions", []) if isinstance(a, dict)]
            log.info("Server accepted capabilities; commands it may send: %s", actions)
            if message.get("unknown"):
                log.info("Server has no actions for: %s", message["unknown"])
            return

        if message_type == "error":
            log.warning("Server error: %s", message.get("error"))
            return

        # hello, speech.end, memory.suggest, language_model.* — informational.
        log.debug("Server message: %s", message_type)

    async def process(self, event: Event) -> None:
        """
        Forward one microphone frame to the server.

        Deliberately unconditional. There used to be an RMS gate here that
        dropped anything below a fixed threshold, which decided what the
        server was allowed to hear using the weakest CPU in the system and no
        knowledge of the conversation. It also clipped word onsets, because a
        frame is only sent *after* it crosses the threshold, and the start of
        a word is quiet. The server holds a rolling buffer and reaches
        backwards instead, so nothing needs discarding here.

        16 kHz mono costs 32 KB/s — a rounding error on any WiFi link.
        """
        if not self._send_allowed.is_set():
            return

        audio_frame = event.data
        if audio_frame is None:
            return

        # While disconnected, drop rather than accumulate: a backlog would be
        # flushed at the server on reconnect as a burst of stale speech.
        if self._websocket is None:
            return

        try:
            self._outbox.put_nowait(audio_frame)
        except asyncio.QueueFull:
            # Stay real-time: the newest audio matters more than the oldest.
            while not self._outbox.empty():
                self._outbox.get_nowait()
            self._outbox.put_nowait(audio_frame)
