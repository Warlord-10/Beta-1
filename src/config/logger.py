"""Beta-1 — Logging setup.

Reads LOG_MODE and LOG_FILE_PATH from settings to decide where logs go.
Usage:
    from src.config.logger import get_logger
    logger = get_logger(__name__)
    logger.info("hello")
"""

from __future__ import annotations

import logging
import os

from src.config.settings import LOG_MODE, LOG_FILE_PATH

_ROOT_LOGGER_NAME = "beta1"

# Shared formatter
_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def _setup_root_logger() -> logging.Logger:
    """Configure the root `beta1` logger once."""
    logger = logging.getLogger(_ROOT_LOGGER_NAME)

    # Guard against double-init (module may be imported several times)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    mode = LOG_MODE.lower().strip()

    # --- Terminal handler ---
    if mode in ("terminal", "both"):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    # --- File handler ---
    if mode in ("file", "both"):
        log_dir = os.path.dirname(LOG_FILE_PATH)
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Fallback: if an invalid mode was set, at least print to terminal
    if not logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.WARNING)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        logger.warning(
            "Unknown LOG_MODE '%s' — falling back to terminal logging.", LOG_MODE
        )

    return logger


# Initialise once on first import
_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``beta1`` namespace.

    Example:
        >>> logger = get_logger("agents.file_agent")
        # creates logger named "beta1.agents.file_agent"
    """
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
