# Learning tests — verify assumptions about tomllib behavior.
# If these break on upgrade, our code likely needs updating.
#
# Guild depends on:
#   - [a.b] parses as nested dicts {"a": {"b": ...}}
#   - [[items]] parses as array of tables
#   - Missing file raises FileNotFoundError (not empty dict)
#   - Invalid TOML raises tomllib.TOMLDecodeError

from __future__ import annotations

import tomllib

import pytest


@pytest.mark.unit
class TestNestedTablesParseAsNestedDicts:
    """Verify [a.b] becomes {"a": {"b": ...}} — used for guild.toml config."""

    def test_nested_tables_parse_as_nested_dicts(self) -> None:
        toml_str = b"""
[provider]
backend = "ollama"

[provider.ollama]
base_url = "http://localhost:11434"
model = "qwen2.5-coder:7b"
"""
        data = tomllib.loads(toml_str.decode())
        assert isinstance(data["provider"], dict)
        assert data["provider"]["backend"] == "ollama"
        assert isinstance(data["provider"]["ollama"], dict)
        assert data["provider"]["ollama"]["base_url"] == "http://localhost:11434"
        assert data["provider"]["ollama"]["model"] == "qwen2.5-coder:7b"

    def test_deeply_nested_tables(self) -> None:
        toml_str = b"""
[a.b.c]
key = "value"
"""
        data = tomllib.loads(toml_str.decode())
        assert data["a"]["b"]["c"]["key"] == "value"


@pytest.mark.unit
class TestArrayOfTablesParseCorrectly:
    """Verify [[items]] syntax — used for team block definitions."""

    def test_array_of_tables_parse_correctly(self) -> None:
        toml_str = b"""
[[blocks]]
name = "planner"
tier = "scoped"

[[blocks]]
name = "coder"
tier = "autopilot"
"""
        data = tomllib.loads(toml_str.decode())
        assert isinstance(data["blocks"], list)
        assert len(data["blocks"]) == 2
        assert data["blocks"][0]["name"] == "planner"
        assert data["blocks"][1]["name"] == "coder"

    def test_array_of_tables_with_nested_keys(self) -> None:
        toml_str = b"""
[[tools]]
name = "file_read"
[tools.config]
max_size = 1024
"""
        data = tomllib.loads(toml_str.decode())
        assert data["tools"][0]["name"] == "file_read"
        assert data["tools"][0]["config"]["max_size"] == 1024


@pytest.mark.unit
class TestMissingFileRaisesNotReturnsEmpty:
    """Verify opening a missing file raises — not silently returning {}."""

    def test_missing_file_raises_not_returns_empty(self, tmp_path) -> None:
        missing = tmp_path / "nonexistent.toml"
        with pytest.raises(FileNotFoundError):
            with open(missing, "rb") as f:
                tomllib.load(f)

    def test_load_requires_binary_mode(self) -> None:
        """tomllib.load() requires a binary file object — verify the contract."""
        import io

        # Text mode should raise TypeError
        text_stream = io.StringIO("[section]\nkey = 'val'\n")
        with pytest.raises(TypeError):
            tomllib.load(text_stream)  # type: ignore[arg-type]


@pytest.mark.unit
class TestInvalidTomlRaisesDecodeError:
    """Verify invalid TOML raises TOMLDecodeError — used for config validation."""

    def test_invalid_toml_raises_decode_error(self) -> None:
        invalid_toml = b"[broken\nkey = "
        with pytest.raises(tomllib.TOMLDecodeError):
            tomllib.loads(invalid_toml.decode())

    def test_duplicate_key_raises_decode_error(self) -> None:
        duplicate = b"""
[section]
key = "first"
key = "second"
"""
        with pytest.raises(tomllib.TOMLDecodeError):
            tomllib.loads(duplicate.decode())

    def test_empty_string_parses_as_empty_dict(self) -> None:
        """Empty string is valid TOML — returns empty dict."""
        data = tomllib.loads("")
        assert data == {}
