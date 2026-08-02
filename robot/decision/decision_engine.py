"""
decision/decision_engine.py — Decision LLM integration and action generation.

The DecisionEngine is the robot's "brain":
  - Subscribes to perception events to know when to think.
  - Uses ContextBuilder to prepare the LLM input payload.
  - Calls the decision LLM API.
  - Parses the structured action response.
  - Publishes "decision.actions" events for the ActionDispatcher.

The engine runs on a minimum interval to prevent spamming the LLM.
It can also be triggered immediately on new speech input.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from config import DecisionAPIConfig
from core.context_manager import ContextManager
from core.event_bus import Event, EventBus
from decision.context_builder import ContextBuilder
from utils.http_client import join_url, post_json
from utils.logger import get_logger
from utils.retry import async_retry

log = get_logger(__name__)


class DecisionEngine:
    """
    Orchestrates the robot's reasoning cycle.

    Trigger conditions:
      - "perception.speech" event received (human spoke).
      - Periodic timer (proactive behaviour, configurable interval).
      - TODO: "perception.objects" event with notable changes (optional).

    Output:
      - Publishes "decision.actions" events containing a list of raw action dicts.

    Responsibilities:
      - NOT deciding the content of actions (delegated to the LLM).
      - NOT executing actions (delegated to ActionDispatcher via EventBus).
    """

    name = "decision_engine"

    def __init__(
        self,
        event_bus: EventBus,
        context_manager: ContextManager,
        config: DecisionAPIConfig,
    ) -> None:
        """
        Args:
            event_bus:       Shared EventBus.
            context_manager: Shared ContextManager.
            config:          DecisionAPI configuration.
        """
        self.event_bus = event_bus
        self.context = context_manager
        self.config = config
        self._builder = ContextBuilder(context_manager)
        self._task: Optional[asyncio.Task] = None
        self._last_decision_time: float = 0.0
        self._pending_trigger = asyncio.Event()  # Set when speech arrives

    async def start(self) -> None:
        """
        Subscribe to perception events and start the decision loop.
        """
        if self.config.enabled:
            self.event_bus.subscribe("perception.speech", self._on_speech)
            self._task = asyncio.create_task(self._decision_loop(), name="decision_loop")
            log.info("DecisionEngine started.")
        else:
            log.info("DecisionEngine disabled.")

    async def stop(self) -> None:
        """
        Unsubscribe and cancel the decision loop task.
        """
        self.event_bus.unsubscribe("perception.speech", self._on_speech)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("DecisionEngine stopped.")

    async def _on_speech(self, event: Event) -> None:
        """
        Called when a "perception.speech" event arrives.

        Signals the decision loop to run immediately.

        Args:
            event: Speech event with transcribed text as data.
        """
        log.debug("DecisionEngine triggered by speech: %r", event.data)
        self._pending_trigger.set()

    async def _decision_loop(self) -> None:
        """
        Main reasoning loop.

        Waits for either:
          - A speech trigger (immediate response)
          - The periodic interval (proactive behaviour)

        On trigger, calls the LLM and dispatches the resulting actions.
        """
        while True:
            try:
                # Wait for trigger OR periodic interval, whichever comes first.
                try:
                    await asyncio.wait_for(
                        self._pending_trigger.wait(),
                        timeout=self.config.timeout_seconds,  # Periodic fallback
                    )
                except asyncio.TimeoutError:
                    pass  # Periodic tick — still proceed to decide

                self._pending_trigger.clear()

                # Enforce minimum interval between LLM calls.
                now = time.monotonic()
                elapsed = now - self._last_decision_time
                min_interval = self.config.timeout_seconds  # Reuse as min gap for now
                # TODO: Use a dedicated config field: config.decision_min_interval_seconds

                if elapsed < 1.0:  # Hard minimum: don't call LLM more than once/sec
                    await asyncio.sleep(1.0 - elapsed)

                await self._run_decision_cycle()
                self._last_decision_time = time.monotonic()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Unexpected error in decision loop: %s", exc)
                await asyncio.sleep(2.0)  # Back off on error

    async def _run_decision_cycle(self) -> None:
        """
        Execute one full reasoning cycle:
          1. Build context payload.
          2. Call decision LLM API.
          3. Parse actions from response.
          4. Publish "decision.actions" event.
        """
        log.debug("Running decision cycle.")
        payload = self._builder.build()

        try:
            response = await async_retry(
                self._call_llm_api,
                payload,
                retries=2,
                base_delay=1.0,
            )
        except Exception as exc:
            log.error("Decision LLM API call failed: %s", exc)
            return

        raw_actions = response.get("actions", [])
        if not raw_actions:
            log.debug("Decision LLM returned no actions.")
            return

        log.info("Decision LLM returned %d action(s).", len(raw_actions))
        await self.event_bus.publish(
            Event(
                topic="decision.actions",
                data=raw_actions,
                source=self.name,
            )
        )

    async def _call_llm_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send the context payload to the decision LLM API and return the response.

        Args:
            payload: The context payload built by ContextBuilder.

        Returns:
            Parsed JSON response dict containing "actions" list.

        """
        url = join_url(self.config.base_url, self.config.endpoint)
        data = await post_json(
            url=url,
            payload=payload,
            timeout_seconds=self.config.timeout_seconds,
        )
        return data if isinstance(data, dict) else {"actions": []}
