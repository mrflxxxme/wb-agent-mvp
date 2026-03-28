"""
Centralized logging setup.
Call setup_logging() once at the very start of main() before anything else.
"""
from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
        force=True,
    )

    # Suppress verbose third-party loggers
    for noisy_logger in ["httpx", "apscheduler", "telegram", "urllib3", "google"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    return logging.getLogger("wb_agent")
