"""Structured logging configuration for Guild (REQ-11.3)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

__all__ = [
    "StructuredFormatter",
    "configure_logging",
]


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter."""

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
    """Configure Guild's logging with structured JSON output.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        structured: If True, use JSON formatter; otherwise use standard format.
    """
    root_logger = logging.getLogger("guild")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on re-configuration
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root_logger.addHandler(handler)
