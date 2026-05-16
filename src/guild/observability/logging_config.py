"""Structured logging configuration for Guild (REQ-11.3).

Delegates to logger_python for consistent structured logging across all
lightshield projects.  The configure_logging() function remains the single
entry point used by CLI and daemon bootstrap code.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from logger_python import configure

__all__ = [
    "StructuredFormatter",
    "configure_logging",
]


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter.

    Retained for backward compatibility with code that references this class
    directly.  New code should rely on logger_python's built-in formatting.
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
    """Configure Guild's logging via logger_python.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        structured: If True, use JSON formatter; otherwise use standard format.
    """
    configure(name="guild", level=level, structured=structured)
