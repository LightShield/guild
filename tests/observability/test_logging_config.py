"""Tests for observability/logging_config.py — structured logging (REQ-11.3)."""

from __future__ import annotations

import json
import logging

import pytest

from guild.observability.logging_config import StructuredFormatter, configure_logging


@pytest.mark.unit
class TestConfigureLogging:
    """configure_logging sets up the guild logger correctly."""

    def test_sets_logger_level(self) -> None:
        """configure_logging sets the requested level on the guild logger."""
        configure_logging(level="DEBUG", structured=False)
        guild_logger = logging.getLogger("guild")
        assert guild_logger.level == logging.DEBUG

    def test_structured_mode_uses_json_formatter(self) -> None:
        """In structured mode, the handler uses StructuredFormatter."""
        configure_logging(level="INFO", structured=True)
        guild_logger = logging.getLogger("guild")
        assert len(guild_logger.handlers) == 1
        assert isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

    def test_non_structured_mode_uses_standard_formatter(self) -> None:
        """In non-structured mode, the handler uses standard Formatter."""
        configure_logging(level="INFO", structured=False)
        guild_logger = logging.getLogger("guild")
        assert len(guild_logger.handlers) == 1
        assert not isinstance(guild_logger.handlers[0].formatter, StructuredFormatter)

    def test_clears_existing_handlers_on_reconfigure(self) -> None:
        """Calling configure_logging twice does not duplicate handlers."""
        configure_logging(level="INFO", structured=True)
        configure_logging(level="WARNING", structured=True)
        guild_logger = logging.getLogger("guild")
        assert len(guild_logger.handlers) == 1


@pytest.mark.unit
class TestStructuredFormatter:
    """StructuredFormatter produces valid JSON log entries."""

    def test_format_produces_valid_json(self) -> None:
        """format() output is valid JSON with expected keys."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="guild.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "guild.test"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed


# ======================================================================
# StructuredFormatter with exception (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestStructuredFormatterException:
    """StructuredFormatter formatting with exc_info."""

    def test_format_with_exception(self) -> None:
        """Log records with exc_info include an 'exception' key in output."""
        formatter = StructuredFormatter()
        try:
            raise ValueError("test boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="guild.test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="Something failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "test boom" in parsed["exception"]
