"""
core/service_registry.py — Lifecycle management for robot services.

Every major component (sensors, perception clients, decision engine, etc.)
is a "service" with start() and stop() coroutines.

The ServiceRegistry owns all registered services and provides uniform
startup and shutdown, including ordering and error isolation.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Protocol, runtime_checkable

from utils.logger import get_logger

log = get_logger(__name__)


@runtime_checkable
class Service(Protocol):
    """
    Protocol that all robot services must implement.

    Services are started in registration order and stopped in reverse order.
    Each service is responsible for its own internal async tasks.
    """

    name: str  # Unique human-readable service name

    async def start(self) -> None:
        """
        Initialize resources and begin background tasks.

        Called once by the ServiceRegistry during robot startup.
        Must not block indefinitely — use asyncio.create_task() for loops.
        """
        ...

    async def stop(self) -> None:
        """
        Cancel background tasks and release resources.

        Called once by the ServiceRegistry during robot shutdown.
        Should be idempotent.
        """
        ...


class ServiceRegistry:
    """
    Manages the lifecycle of all robot services.

    Services are started in the order they were registered.
    Services are stopped in reverse order (LIFO), ensuring clean teardown.

    Usage:
        registry = ServiceRegistry()
        registry.register(camera_sensor)
        registry.register(vision_client)
        ...
        await registry.start_all()
        ...
        await registry.stop_all()
    """

    def __init__(self) -> None:
        self._services: List[Service] = []
        self._service_map: Dict[str, Service] = {}
        self._running: bool = False

    def register(self, service: Service) -> None:
        """
        Register a service.

        Args:
            service: An object implementing the Service protocol.

        Raises:
            ValueError: If a service with the same name is already registered.
        """
        if service.name in self._service_map:
            raise ValueError(f"Service '{service.name}' is already registered.")
        self._services.append(service)
        self._service_map[service.name] = service
        log.debug("Registered service: %s", service.name)

    def get(self, name: str) -> Optional[Service]:
        """
        Retrieve a registered service by name.

        Args:
            name: The service's unique name.

        Returns:
            The service instance, or None if not found.
        """
        return self._service_map.get(name)

    async def start_all(self) -> None:
        """
        Start all registered services in registration order.

        If a service raises during start(), the exception is logged and
        startup continues with remaining services. Partial startup is
        intentional so the robot can operate with degraded capabilities.

        TODO: Consider making startup failure policy configurable
              (e.g. "abort on critical service failure").
        """
        log.info("Starting %d service(s)...", len(self._services))
        for service in self._services:
            try:
                log.info("Starting service: %s", service.name)
                await service.start()
            except Exception as exc:
                log.error("Failed to start service '%s': %s", service.name, exc)
        self._running = True
        log.info("All services started.")

    async def stop_all(self) -> None:
        """
        Stop all registered services in reverse order.

        Exceptions during stop() are logged but do not interrupt teardown.
        """
        log.info("Stopping services...")
        for service in reversed(self._services):
            try:
                log.info("Stopping service: %s", service.name)
                await service.stop()
            except Exception as exc:
                log.error("Error stopping service '%s': %s", service.name, exc)
        self._running = False
        log.info("All services stopped.")

    @property
    def is_running(self) -> bool:
        """True if start_all() has been called without a subsequent stop_all()."""
        return self._running
