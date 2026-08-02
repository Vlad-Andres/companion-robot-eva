"""
runtime.py — Central RobotRuntime orchestrator.

The RobotRuntime owns the full agent lifecycle:
  - Constructs and wires all subsystems.
  - Starts all services via ServiceRegistry.
  - Connects the ActionDispatcher to the EventBus.
  - Runs the continuous agent loop.
  - Handles graceful shutdown on signal or KeyboardInterrupt.

This is the single "god object" intentionally — it's the composition root
that wires all loosely coupled components together.

Data flow summary:
    Microphone → EventBus → SpeechClient → server (WebSocket)
    server replies → EventBus → runtime handlers → ActionDispatcher → Handlers
"""

from __future__ import annotations

import asyncio
import signal
import time

from config import RobotConfig
from core.action_dispatcher import ActionDispatcher
from core.event_bus import Event, EventBus
from core.service_registry import ServiceRegistry
from utils.logger import get_logger

log = get_logger(__name__)
eyes_log = get_logger("EYES")


class RobotRuntime:
    """
    Central orchestrator for the companion robot.

    Constructs the dependency graph of all robot subsystems,
    starts them in order, runs the agent loop, and tears them down cleanly.

    Usage:
        config = RobotConfig()
        runtime = RobotRuntime(config)
        asyncio.run(runtime.run())
    """

    def __init__(self, config: RobotConfig) -> None:
        """
        Wire all subsystems together.

        All construction happens here — no lazy initialization.
        This makes the dependency graph explicit and testable.

        Args:
            config: Fully populated RobotConfig instance.
        """
        self.config = config
        self._shutdown_event = asyncio.Event()

        # ------------------------------------------------------------------
        # Core infrastructure
        # ------------------------------------------------------------------
        self.event_bus = EventBus()
        self.service_registry = ServiceRegistry()
        self.action_dispatcher = ActionDispatcher()

        # ------------------------------------------------------------------
        # Display (eye controller)
        # ------------------------------------------------------------------
        self.eye_controller = self._init_eye_controller()

        # ------------------------------------------------------------------
        # Action handlers — registered with dispatcher
        # ------------------------------------------------------------------
        self._register_action_handlers()

        # ------------------------------------------------------------------
        # Sensors
        # ------------------------------------------------------------------
        self._register_sensors()

        # ------------------------------------------------------------------
        # Perception clients
        # ------------------------------------------------------------------
        self._register_perception_clients()

        # ------------------------------------------------------------------
        # Idle behaviors (autonomous reflex behavior)
        # ------------------------------------------------------------------
        self._register_idle_behaviors()

        # ------------------------------------------------------------------
        # Subscribe action dispatcher to decision.actions events
        # ------------------------------------------------------------------
        self.event_bus.subscribe("decision.actions", self._on_decision_actions)
        self.event_bus.subscribe("perception.backend_do", self._on_backend_do)
        self.event_bus.subscribe("perception.backend_command", self._on_backend_command)
        self.event_bus.subscribe("perception.backend_speech", self._on_backend_speech)
        self.event_bus.subscribe("perception.backend_audio", self._on_backend_audio)
        self.event_bus.subscribe("perception.backend_listening", self._on_backend_listening)
        self.event_bus.subscribe("perception.backend_waiting", self._on_backend_waiting)

        self._backend_feedback_lock = asyncio.Lock()
        self._backend_audio_playback_lock = asyncio.Lock()
        self._backend_feedback_busy_until: float = 0.0
        self._listening_side: int = 0
        self._thinking_task: asyncio.Task | None = None

        log.info("RobotRuntime initialized.")

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _init_eye_controller(self):
        """
        Initialize the OLED eye controller.

        Returns None if the display is unavailable (e.g. running on desktop).
        """
        try:
            from display.eye_controller import EyeController
            eye_controller = EyeController(
                port=self.config.display.i2c_port,
                addr=self.config.display.i2c_address,
            )
            log.info("EyeController initialized.")
            return eye_controller
        except Exception as exc:
            log.warning("Could not initialize EyeController: %s — display disabled.", exc)
            return None

    def _register_action_handlers(self) -> None:
        """Register all action handlers with the ActionDispatcher."""
        from actions.eye_expression_handler import EyeAnimationHandler, EyeExpressionHandler

        self.action_dispatcher.register_handler(
            EyeExpressionHandler(
                eye_controller=self.eye_controller,
                audio_config=self.config.audio,
            )
        )
        self.action_dispatcher.register_handler(
            EyeAnimationHandler(
                eye_controller=self.eye_controller,
                audio_config=self.config.audio,
            )
        )
        log.debug("Action handlers registered.")

    def _register_sensors(self) -> None:
        """Construct and register sensor services."""
        from sensors.microphone_sensor import MicrophoneSensor

        self.service_registry.register(
            MicrophoneSensor(self.event_bus, self.config.microphone)
        )
        log.debug("Sensor services registered.")

    def _register_perception_clients(self) -> None:
        """Construct and register perception client services."""
        from perception.speech_client import SpeechClient

        self.service_registry.register(
            SpeechClient(self.event_bus, self.config.speech_api)
        )
        log.debug("Perception client services registered.")

    def _register_idle_behaviors(self) -> None:
        """Register autonomous idle behaviours (e.g. periodic blinking)."""
        from behaviors.idle_blink import IdleBlinkService

        blink_cfg = self.config.idle_blink
        if blink_cfg.enabled:
            self.service_registry.register(
                IdleBlinkService(
                    event_bus=self.event_bus,
                    min_interval=blink_cfg.min_interval_seconds,
                    max_interval=blink_cfg.max_interval_seconds,
                    long_blink_chance=blink_cfg.long_blink_chance,
                )
            )
            log.debug("IdleBlinkService registered.")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_decision_actions(self, event: Event) -> None:
        """
        Called when a behavior publishes a "decision.actions" event.

        Forwards the raw action list to the ActionDispatcher.

        Args:
            event: Event with data = List[dict] of raw action objects.
        """
        raw_actions = event.data or []
        await self.action_dispatcher.dispatch_raw(raw_actions)

    async def _try_reserve_backend_feedback(self, duration_seconds: float) -> bool:
        async with self._backend_feedback_lock:
            now = time.monotonic()
            if now < self._backend_feedback_busy_until:
                eyes_log.debug(
                    "busy_drop_backend_feedback remaining=%.2fs",
                    (self._backend_feedback_busy_until - now),
                )
                return False
            self._backend_feedback_busy_until = now + max(0.0, float(duration_seconds))
            eyes_log.debug("reserve_backend_feedback duration=%.2fs", duration_seconds)
            return True

    def _cancel_thinking(self) -> None:
        if self._thinking_task and not self._thinking_task.done():
            self._thinking_task.cancel()
        self._thinking_task = None

    async def _on_backend_do(self, event: Event) -> None:
        command = str(event.data or "").strip()
        if not command:
            return

        if not await self._try_reserve_backend_feedback(duration_seconds=1.6):
            return

        eyes_log.info("backend_do command=%s", command)
        self._cancel_thinking()
        await self.action_dispatcher.dispatch_raw(
            [{"type": "set_eye_expression", "payload": {"expression": "curious"}}]
        )

    async def _on_backend_command(self, event: Event) -> None:
        """
        Execute one structured command from the server.

        Envelope shape is defined in server/protocol.py: {name, group, args}.
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
        audio_bytes = event.data
        if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
            return

        if not await self._try_reserve_backend_feedback(duration_seconds=2.5):
            return

        async with self._backend_audio_playback_lock:
            eyes_log.info("backend_audio bytes=%d", len(audio_bytes))
            self._cancel_thinking()
            await self.action_dispatcher.dispatch_raw(
                [{"type": "set_eye_expression", "payload": {"expression": "happy"}}]
            )

            await self.event_bus.publish(
                Event(topic="perception.backend_audio_playing", data=None, source="runtime")
            )
            try:
                from utils.audio import play_wav_bytes_blocking

                await asyncio.to_thread(
                    play_wav_bytes_blocking,
                    bytes(audio_bytes),
                    device=self.config.audio.device,
                    volume_percent=self.config.audio.volume_percent,
                    mixer_control=self.config.audio.mixer_control,
                    mixer_card=self.config.audio.mixer_card,
                )
            finally:
                await self.event_bus.publish(
                    Event(topic="perception.backend_audio_done", data=None, source="runtime")
                )

    async def _on_backend_listening(self, _event: Event) -> None:
        if time.monotonic() < self._backend_feedback_busy_until:
            return
        if self._thinking_task is not None:
            return

        self._listening_side = 1 - self._listening_side
        anim = "MOVE_LEFT_BIG" if self._listening_side == 0 else "MOVE_RIGHT_BIG"
        eyes_log.info("listening anim=%s", anim)
        await self.action_dispatcher.dispatch_raw(
            [{"type": "play_eye_animation", "payload": {"animation": anim}}]
        )

    async def _on_backend_waiting(self, _event: Event) -> None:
        if time.monotonic() < self._backend_feedback_busy_until:
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Main entry point — start services, run loop, handle shutdown.

        Call with: asyncio.run(runtime.run())
        """
        log.info("Robot runtime starting up.")

        # Install signal handlers for graceful shutdown.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown_signal)

        # Start all registered services.
        await self.service_registry.start_all()

        # Play startup animation if display is available.
        await self._play_startup_animation()

        log.info("Robot is alive. Press Ctrl+C to shut down.")

        # Block until shutdown is requested.
        await self._shutdown_event.wait()

        # Graceful teardown.
        await self._shutdown()

    async def _play_startup_animation(self) -> None:
        """
        Play the configured startup eye animation.

        Runs the synchronous EyeController call in an executor to avoid
        blocking the event loop.
        """
        if self.eye_controller is None:
            return

        from display.eye_controller import Animation
        animation_name = self.config.runtime.startup_animation.upper()

        try:
            anim = Animation[animation_name]
        except KeyError:
            log.warning("Unknown startup animation '%s' — skipping.", animation_name)
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.eye_controller.play, anim)
        log.info("Startup animation '%s' played.", animation_name)

        # Play startup sound if enabled.
        if self.config.audio.enabled and self.config.audio.startup_sound:
            from utils.audio import play_sound
            play_sound(
                self.config.audio.startup_sound,
                device=self.config.audio.device,
                volume_percent=self.config.audio.volume_percent,
                mixer_control=self.config.audio.mixer_control,
                mixer_card=self.config.audio.mixer_card,
            )

    def _handle_shutdown_signal(self) -> None:
        """Signal handler: request graceful shutdown."""
        log.info("Shutdown signal received.")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """
        Graceful shutdown sequence:
          1. Stop all services.
          2. Clear the display.
        """
        log.info("Shutting down robot runtime...")

        await self.service_registry.stop_all()

        # Clear the eye display.
        if self.eye_controller is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.eye_controller.clear)
            except Exception as exc:
                log.warning("Could not clear eye display: %s", exc)

        log.info("Robot runtime shut down cleanly.")
