"""Logging configuration for DevOpsLens AI.

Provides consistent, readable, and structured logging across the application.
"""

import logging
import sys
from app.config import get_settings


def setup_logging() -> None:
    """Configure root logger with consistent formatting and appropriate log level."""
    settings = get_settings()
    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Format: [Timestamp] [Level] [LoggerName]: Message
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid adding duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger instance for the given module."""
    return logging.getLogger(name)
