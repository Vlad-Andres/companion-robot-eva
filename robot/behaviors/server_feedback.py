"""
behaviors/server_feedback.py — Eye and audio feedback for server replies.

Runs as a background service that reacts to the perception.backend_* events
published by the SpeechClient:

  - backend_command   → execute one structured command from the server
  - backend_speech    → happy eyes when a reply is announced
  - backend_audio     → play the synthesized WAV through the speaker
  - backend_listening → alternating glance animation while audio streams
  - backend_waiting   → thinking/impatient loop while the server is slow

A shared wall-clock reservation (_try_reserve_feedback) keeps overlapping
replies from fighting over the eyes and the speaker.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from core.action_dispatcher import ActionDispatcher
from core.event_bus import Event, EventBus
from utils.audio import AudioOutput
from utils.logger import get_logger

log = get_logger(__name__)
eyes_log = get_logger("EYES")


class ServerFeedbackService:
    """
    Reacts to server replies with eye expressions and audio playback.

    Subscribes to the perception.backend_* topics on start and dispatches
    eye/audio actions through the ActionDispatcher like any other behavior.
    """

    name = "server_feedback"

    def __init__(
        self,
        event_bus: EventBus,
        action_dispatcher: ActionDispatcher,
        audio_output: AudioOutput,
    ) -> None:
        """
        Args:
            event_bus:         Shared EventBus.
            action_dispatcher: Dispatcher used to run eye actions.
            audio_output:      Speaker output for synthesized speech.
        """
        self.event_bus = event_bus
        self.action_dispatcher = action_dispatcher
        self.audio_output = audio_output

        self._feedback_lock = asyncio.Lock()
        self._audio_playback_lock = asyncio.Lock()
        self._feedback_busy_until: float = 0.0
        self._listening_side: int = 0
        self._thinking_task: Optional[asyncio.Task] = None

        self._subscriptions = {
            "perception.backend_command": self._on_backend_command,
            "perception.backend_speech": self._on_backend_speech,
            "perception.backend_audio": self._on_backend_audio,
            "perception.backend_listening": self._on_backend_listening,
            "perception.backend_waiting": self._on_backend_waiting,
            "perception.backend_ready": self._on_backend_ready,
        }

    async def start(self) -> None:
        """Subscribe to the server reply topics."""
        for topic, handler in self._subscriptions.items():
            self.event_bus.subscribe(topic, handler)
        log.info("ServerFeedbackService started.")

    async def stop(self) -> None:
        """Unsubscribe and cancel the thinking animation."""
        for topic, handler in self._subscriptions.items():
            self.event_bus.unsubscribe(topic, handler)
        self._cancel_thinking()
        log.info("ServerFeedbackService stopped.")

    # ------------------------------------------------------------------
    # Shared feedback state
    # ------------------------------------------------------------------

    async def _try_reserve_feedback(self, duration_seconds: float) -> bool:
        async with self._feedback_lock:
            now = time.monotonic()
            if now < self._feedback_busy_until:
                eyes_log.debug(
                    "busy_drop_backend_feedback remaining=%.2fs",
                    (self._feedback_busy_until - now),
                )
                return False
            self._feedback_busy_until = now + max(0.0, float(duration_seconds))
            eyes_log.debug("reserve_backend_feedback duration=%.2fs", duration_seconds)
            return True

    def _cancel_thinking(self) -> None:
        if self._thinking_task and not self._thinking_task.done():
            self._thinking_task.cancel()
        self._thinking_task = None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_backend_command(self, event: Event) -> None:
        """
        Execute one structured command from the server.

        Envelope shape is defined in server/protocol.py: {id, name, args}.
        """
        command = event.data
        if not isinstance(command, dict):
            return

        name = str(command.get("name") or "")
        args = command.get("args")
        if not isinstance(args, dict):
            args = {}

        if name == "speak":
            text = str(args.get("text") or "").strip()
            if not text:
                return
            # No local TTS exists; audible replies arrive as server-synthesized
            # WAV. Log so rule confirmations are visible during bring-up.
            log.info("Command speak: %r (no local TTS — silent)", text)
            return

        if name == "move_base":
            movement = str(args.get("command") or "")
            # No motor handler exists yet; surface the command so it is visible
            # during bring-up rather than silently dropped.
            log.info("Command move_base: %s (no motor handler yet)", movement)
            await self.action_dispatcher.dispatch_raw(
                [{"type": "set_eye_expression", "payload": {"expression": "curious"}}]
            )
            return

        log.warning("Unhandled command from server: %s args=%s", name, args)

    async def _on_backend_speech(self, event: Event) -> None:
        text = str(event.data or "").strip()
        if not text:
            return

        # Deliberately no feedback reservation here: this event announces the
        # reply text (speech.start), and the audible WAV follows moments later
        # on backend_audio. Reserving a window here could make backend_audio
        # drop the WAV when synthesis finishes inside it.
        eyes_log.info("backend_speech len=%d", len(text))
        self._cancel_thinking()
        await self.action_dispatcher.dispatch_raw(
            [{"type": "set_eye_expression", "payload": {"expression": "happy"}}]
        )

    async def _on_backend_audio(self, event: Event) -> None:
        """
        Play one piece of synthesized speech, in order, never dropped.

        A reply arrives as several WAVs now — one per sentence, as the model
        writes them. The busy-window used to guard this, which drops anything
        arriving inside it, so every sentence after the first would vanish.
        Speech queues instead; only the eye feedback is throttled.
        """
        audio_bytes = event.data
        if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
            return

        async with self._audio_playback_lock:
            eyes_log.info("backend_audio bytes=%d", len(audio_bytes))
            self._cancel_thinking()
            # Hold the eye-feedback window open for as long as we are talking,
            # so glances and blinks do not fight the speaking face.
            await self._try_reserve_feedback(duration_seconds=2.5)
            await self.action_dispatcher.dispatch_raw(
                [{"type": "set_eye_expression", "payload": {"expression": "happy"}}]
            )

            await self.event_bus.publish(
                Event(topic="perception.backend_audio_playing", data=None, source=self.name)
            )
            try:
                await asyncio.to_thread(self.audio_output.play_speech, bytes(audio_bytes))
            finally:
                await self.event_bus.publish(
                    Event(topic="perception.backend_audio_done", data=None, source=self.name)
                )

    async def _on_backend_listening(self, _event: Event) -> None:
        if time.monotonic() < self._feedback_busy_until:
            return
        if self._thinking_task is not None:
            return

        self._listening_side = 1 - self._listening_side
        anim = "MOVE_LEFT_BIG" if self._listening_side == 0 else "MOVE_RIGHT_BIG"
        eyes_log.info("listening anim=%s", anim)
        await self.action_dispatcher.dispatch_raw(
            [{"type": "play_eye_animation", "payload": {"animation": anim}}]
        )

    async def _on_backend_ready(self, _event: Event) -> None:
        """The turn is finished — stop looking like she is still working."""
        self._cancel_thinking()

    async def _on_backend_waiting(self, _event: Event) -> None:
        if time.monotonic() < self._feedback_busy_until:
            return
        if self._thinking_task is not None and not self._thinking_task.done():
            return

        eyes_log.info("thinking start")

        async def _loop() -> None:
            try:
                while True:
                    await self.action_dispatcher.dispatch_raw(
                        [{"type": "set_eye_expression", "payload": {"expression": "thinking"}}]
                    )
                    await asyncio.sleep(2.2)

                    await self.action_dispatcher.dispatch_raw(
                        [{"type": "set_eye_expression", "payload": {"expression": "impatient"}}]
                    )
                    await asyncio.sleep(3.3)
            except asyncio.CancelledError:
                pass

        self._thinking_task = asyncio.create_task(_loop())
