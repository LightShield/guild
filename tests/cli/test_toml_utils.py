"""Tests for cli/toml_utils.py — TOML serialization and parsing (REQ-01.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guild.cli.toml_utils import load_toml, parse_value, toml_value, write_toml


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestParseValue:
    """parse_value infers Python types from string values."""

    def test_parses_true(self) -> None:
        """'true' (case-insensitive) parses to bool True."""
        assert parse_value("true") is True
        assert parse_value("True") is True
        assert parse_value("TRUE") is True

    def test_parses_false(self) -> None:
        """'false' (case-insensitive) parses to bool False."""
        assert parse_value("false") is False
        assert parse_value("False") is False

    def test_parses_integer(self) -> None:
        """Numeric strings parse to int."""
        assert parse_value("42") == 42
        assert isinstance(parse_value("42"), int)

    def test_parses_float(self) -> None:
        """Decimal strings parse to float."""
        assert parse_value("3.14") == pytest.approx(3.14)
        assert isinstance(parse_value("3.14"), float)

    def test_non_numeric_returns_string(self) -> None:
        """Non-numeric, non-boolean strings are returned as-is."""
        assert parse_value("hello") == "hello"
        assert parse_value("llama3") == "llama3"

    def test_negative_integer(self) -> None:
        """Negative integers are parsed correctly."""
        assert parse_value("-7") == -7

    def test_empty_string_returns_string(self) -> None:
        """An empty string stays a string."""
        assert parse_value("") == ""


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestTomlValue:
    """toml_value formats Python values as TOML literals."""

    def test_formats_bool_true(self) -> None:
        """True becomes 'true'."""
        assert toml_value(True) == "true"

    def test_formats_bool_false(self) -> None:
        """False becomes 'false'."""
        assert toml_value(False) == "false"

    def test_formats_string_with_quotes(self) -> None:
        """Strings are double-quoted."""
        assert toml_value("hello") == '"hello"'

    def test_formats_integer(self) -> None:
        """Integers are formatted without quotes."""
        assert toml_value(42) == "42"

    def test_formats_float(self) -> None:
        """Floats are formatted without quotes."""
        assert toml_value(3.14) == "3.14"


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestWriteAndLoadToml:
    """write_toml and load_toml round-trip data correctly."""

    def test_round_trip_scalars(self, tmp_path: Path) -> None:
        """Top-level scalar values survive a write-then-load cycle."""
        path = tmp_path / "config.toml"
        data = {"model": "llama3", "timeout": 60}
        write_toml(path, data)
        loaded = load_toml(path)
        assert loaded["model"] == "llama3"
        assert loaded["timeout"] == 60

    def test_round_trip_nested_table(self, tmp_path: Path) -> None:
        """Nested tables (sections) survive a write-then-load cycle."""
        path = tmp_path / "config.toml"
        data = {"provider": {"name": "ollama", "base_url": "http://localhost:11434"}}
        write_toml(path, data)
        loaded = load_toml(path)
        assert loaded["provider"]["name"] == "ollama"
        assert loaded["provider"]["base_url"] == "http://localhost:11434"

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """Loading a non-existent file returns {}."""
        path = tmp_path / "missing.toml"
        assert load_toml(path) == {}

    def test_round_trip_booleans(self, tmp_path: Path) -> None:
        """Boolean values survive a write-then-load cycle."""
        path = tmp_path / "config.toml"
        data = {"verbose": True, "quiet": False}
        write_toml(path, data)
        loaded = load_toml(path)
        assert loaded["verbose"] is True
        assert loaded["quiet"] is False
