from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    level = os.getenv("ROBOT_BACKEND_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
