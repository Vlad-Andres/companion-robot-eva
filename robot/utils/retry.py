"""
utils/retry.py — Async retry helper.

Use async_retry() to wrap any coroutine that calls an external API,
providing automatic retries with exponential backoff on failure.
"""

import asyncio
import functools
from typing import Any, Callable, Optional, Tuple, Type

from utils.logger import get_logger

log = get_logger(__name__)


async def async_retry(
    coro_func: Callable,
    *args,
    retries: int = 3,
    base_delay: float = 0.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    **kwargs,
) -> Any:
    """
    Call an async function with automatic retries and exponential backoff.

    Args:
        coro_func: The async function to call.
        *args:     Positional arguments forwarded to coro_func.
        retries:   Maximum number of retry attempts after initial failure.
        base_delay: Initial delay in seconds (doubles each retry).
        exceptions: Tuple of exception types to catch and retry on.
        **kwargs:  Keyword arguments forwarded to coro_func.

    Returns:
        The return value of coro_func on success.

    Raises:
        The last caught exception if all retries are exhausted.

    Example:
        result = await async_retry(my_api_client.call, data, retries=3)
    """
    last_exc: Optional[Exception] = None
    delay = base_delay

    for attempt in range(retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt < retries:
                log.warning(
                    "Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                    attempt + 1,
                    retries + 1,
                    getattr(coro_func, "__name__", str(coro_func)),
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                log.error(
                    "All %d attempts failed for %s: %s",
                    retries + 1,
                    getattr(coro_func, "__name__", str(coro_func)),
                    exc,
                )

    raise last_exc  # type: ignore[misc]
