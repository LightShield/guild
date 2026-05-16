"""Vendored logger_python — thin wrapper over stdlib logging.

Provides:
- get_logger(name) -> logging.Logger
- configure(name=..., level=..., structured=False) -> sets up handlers/formatters
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

__all__ = ["configure", "get_logger"]


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return logging.getLogger(name)


class _StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for structured=True mode."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON object."""
        log_entry = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def configure(
    name: str = "root",
    level: str | int = "INFO",
    structured: bool = False,
) -> None:
    """Configure logging for the specified logger name.

    Args:
        name: Logger name to configure.
        level: Log level (string or int).
        structured: If True, use JSON formatter; otherwise standard format.
    """
    logger = logging.getLogger(name)

    # Convert string level to int
    if isinstance(level, str):
        numeric_level = getattr(logging, level.upper(), logging.INFO)
    else:
        numeric_level = level

    logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplication
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)

    if structured:
        formatter = _StructuredFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Prevent propagation to root to avoid duplicate messages
    logger.propagate = False
