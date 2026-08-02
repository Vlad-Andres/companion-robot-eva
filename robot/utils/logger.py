"""
utils/logger.py — Structured logging setup.

Provides a get_logger() factory used by every module.
Logging format and level are controlled by RuntimeConfig.log_level.
"""

import logging
import sys
from typing import Optional


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_root_configured = False


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logger once at startup.

    Call this from main.py before any other module logs.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
    """
    global _root_configured
    if _root_configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.addHandler(handler)
    _root_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A configured Logger instance.

    Example:
        log = get_logger(__name__)
        log.info("Service started")
    """
    return logging.getLogger(name)
