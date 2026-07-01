"""Logging configuration.

A single ``configure_logging`` entry point so the format/level are consistent
across the API process and any worker code. Call once at startup.
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging exactly once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)

    # Third-party loggers are noisy at DEBUG; keep them at WARNING.
    for noisy in ("pylint", "bandit", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger (configures logging lazily if needed)."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
