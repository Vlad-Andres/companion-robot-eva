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
    Sensors → EventBus → Perception → ContextManager
    ContextManager → DecisionEngine → EventBus → ActionDispatcher → Handlers
"""

from __future__ import annotations

import asyncio
import signal
from typing import Optional

from config import RobotConfig
from core.action_dispatcher import ActionDispatcher
from core.context_manager import ContextManager
from core.event_bus import Event, EventBus
from core.service_registry import ServiceRegistry
from memory.memory_store import MemoryStore
from utils.logger import configure_logging, get_logger

log = get_logger(__name__)


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
        self.context_manager = ContextManager(
            max_history_turns=config.decision_api.max_history_turns
        )
        self.memory_store = MemoryStore(
            capacity=config.memory.short_term_capacity,
            long_term_path=config.memory.long_term_path,
        )
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
        # Decision engine
        # ------------------------------------------------------------------
        self._register_decision_engine()

        # ------------------------------------------------------------------
        # Idle behaviors (autonomous reflex behavior)
        # ------------------------------------------------------------------
        self._register_idle_behaviors()

        # ------------------------------------------------------------------
        # Subscribe action dispatcher to decision.actions events
        # ------------------------------------------------------------------
        self.event_bus.subscribe("decision.actions", self._on_decision_actions)

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
        from actions.speak_handler import SpeakHandler
        from actions.eye_expression_handler import EyeAnimationHandler, EyeExpressionHandler

        self.action_dispatcher.register_handler(
            SpeakHandler(context_manager=self.context_manager)
        )
        self.action_dispatcher.register_handler(
            EyeExpressionHandler(
                eye_controller=self.eye_controller,
                context_manager=self.context_manager,
            )
        )
        self.action_dispatcher.register_handler(
            EyeAnimationHandler(
                eye_controller=self.eye_controller,
                context_manager=self.context_manager,
            )
        )
        log.debug("Action handlers registered.")

    def _register_sensors(self) -> None:
        """Construct and register sensor services."""
        from sensors.camera_sensor import CameraSensor
        from sensors.microphone_sensor import MicrophoneSensor

        self.service_registry.register(
            CameraSensor(self.event_bus, self.config.camera)
        )
        self.service_registry.register(
            MicrophoneSensor(self.event_bus, self.config.microphone)
        )
        log.debug("Sensor services registered.")

    def _register_perception_clients(self) -> None:
        """Construct and register perception client services."""
        from perception.speech_client import SpeechClient
        from perception.vision_client import VisionClient

        self.service_registry.register(
            VisionClient(self.event_bus, self.context_manager, self.config.vision_api)
        )
        self.service_registry.register(
            SpeechClient(self.event_bus, self.context_manager, self.config.speech_api)
        )
        log.debug("Perception client services registered.")

    def _register_decision_engine(self) -> None:
        """Construct and register the decision engine service."""
        from decision.decision_engine import DecisionEngine

        self.decision_engine = DecisionEngine(
            self.event_bus,
            self.context_manager,
            self.config.decision_api,
        )
        self.service_registry.register(self.decision_engine)
        log.debug("Decision engine registered.")

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
        Called when the DecisionEngine publishes a "decision.actions" event.

        Forwards the raw action list to the ActionDispatcher.

        Args:
            event: Event with data = List[dict] of raw action objects.
        """
        raw_actions = event.data or []
        await self.action_dispatcher.dispatch_raw(raw_actions)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Main entry point — start services, run loop, handle shutdown.

        Call with: asyncio.run(runtime.run())
        """
        log.info("Robot runtime starting up.")
        self.memory_store.load()

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

    def _handle_shutdown_signal(self) -> None:
        """Signal handler: request graceful shutdown."""
        log.info("Shutdown signal received.")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """
        Graceful shutdown sequence:
          1. Stop all services.
          2. Clear the display.
          3. Save memory.
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

        # Persist memory.
        self.memory_store.save()

        log.info("Robot runtime shut down cleanly.")
