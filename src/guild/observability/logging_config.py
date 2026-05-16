"""Structured logging configuration for Guild (REQ-11.3).

Provides configure_logging() as the single entry point used by CLI and
daemon bootstrap code for setting up structured or plain logging.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

__all__ = [
    "StructuredFormatter",
    "configure_logging",
]


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter.

    Produces JSON objects with timestamp, level, logger, message, and
    optionally exception fields.
    """

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


def configure_logging(
    level: str = "INFO",
    structured: bool = True,
) -> None:
    """Configure Guild's logging subsystem.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        structured: If True, use JSON formatter; otherwise use standard format.
    """
    logger = logging.getLogger("guild")

    # Convert string level to int
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Clear existing handlers to avoid duplication
    logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)

    if structured:
        formatter: logging.Formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
