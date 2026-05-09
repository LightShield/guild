"""Tests for dedicated typed tools over generic shell (REQ-08.2).

REQ-08.2: Purpose-built tools (file_read, file_write) rather than generic shell.
This verifies that each tool has its own validation, structured output, and
does not delegate to a shell subprocess.
"""

from __future__ import annotations

import pytest

from guild.tools.base import TOOL_SCHEMAS, ToolResult
from guild.tools.file_ops import execute_file_read, execute_file_write


@pytest.mark.unit
@pytest.mark.req("REQ-08.2")
class TestDedicatedToolsExist:
    """Verify file_read and file_write exist as independent, typed tools."""

    def test_file_read_is_registered_as_standalone_tool(self) -> None:
        """file_read exists in the schema registry as a first-class tool."""
        assert "file_read" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["file_read"]
        # Not a generic 'shell' or 'exec' wrapper
        assert schema["name"] == "file_read"
        assert "shell" not in schema["description"].lower()
        assert "exec" not in schema["description"].lower()

    def test_file_write_is_registered_as_standalone_tool(self) -> None:
        """file_write exists in the schema registry as a first-class tool."""
        assert "file_write" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["file_write"]
        assert schema["name"] == "file_write"
        assert "shell" not in schema["description"].lower()
        assert "exec" not in schema["description"].lower()

    def test_no_unguarded_generic_shell_tool_registered(self) -> None:
        """No unguarded generic exec/run/bash tool exists in schemas.

        The 'shell' tool is intentional (REQ-08.3) but is guarded by a
        denylist and timeout. Other generic names should not exist.
        """
        # 'shell' is allowed — it has safety guards (REQ-08.5, REQ-08.7)
        forbidden_names = {"exec", "run", "execute", "bash", "sh", "command"}
        registered = set(TOOL_SCHEMAS.keys())
        overlap = registered & forbidden_names
        assert overlap == set(), (
            f"Unguarded generic shell tools found: {overlap}. "
            "REQ-08.2 requires dedicated typed tools."
        )


@pytest.mark.unit
@pytest.mark.req("REQ-08.2")
class TestFileReadValidation:
    """file_read has built-in validation — not raw shell behavior."""

    async def test_validates_path_existence_before_reading(self, tmp_path) -> None:
        """file_read checks if the file exists, returns structured error."""
        result = await execute_file_read(
            {"path": str(tmp_path / "does_not_exist.txt")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_validates_path_is_file_not_directory(self, tmp_path) -> None:
        """file_read rejects directories with a structured error."""
        d = tmp_path / "subdir"
        d.mkdir()
        result = await execute_file_read(
            {"path": str(d)},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not a file" in result.error.lower()

    async def test_validates_path_argument_is_present(self) -> None:
        """file_read rejects calls with missing 'path' argument."""
        result = await execute_file_read({})
        assert result.success is False
        assert result.error is not None
        assert "path" in result.error.lower()

    async def test_handles_permission_error_gracefully(self, tmp_path) -> None:
        """file_read returns structured error on permission failure."""
        import os

        p = tmp_path / "noperm.txt"
        p.write_text("secret")
        os.chmod(str(p), 0o000)
        try:
            result = await execute_file_read(
                {"path": str(p)},
                working_dir=str(tmp_path),
            )
            assert result.success is False
            assert result.error is not None
            assert isinstance(result, ToolResult)
        finally:
            os.chmod(str(p), 0o644)


@pytest.mark.unit
@pytest.mark.req("REQ-08.2")
class TestFileWriteValidation:
    """file_write has built-in validation — not raw shell behavior."""

    async def test_validates_path_argument_is_present(self) -> None:
        """file_write rejects calls with missing 'path' argument."""
        result = await execute_file_write({"content": "hello"})
        assert result.success is False
        assert "path" in result.error.lower()

    async def test_validates_content_argument_is_present(self) -> None:
        """file_write rejects calls with missing 'content' argument."""
        result = await execute_file_write({"path": "/tmp/x.txt"})
        assert result.success is False
        assert "content" in result.error.lower()

    async def test_handles_unwritable_path_gracefully(self) -> None:
        """file_write returns structured error for impossible paths."""
        result = await execute_file_write({"path": "/dev/null/subdir/file.txt", "content": "x"})
        assert result.success is False
        assert result.error is not None
        assert isinstance(result, ToolResult)


@pytest.mark.unit
@pytest.mark.req("REQ-08.2")
class TestStructuredOutput:
    """Typed tools produce structured ToolResult, not raw shell output."""

    async def test_file_read_output_is_pure_content(self, tmp_path) -> None:
        """file_read output is the file content, not shell stdout formatting."""
        p = tmp_path / "clean.txt"
        p.write_text("clean content")
        result = await execute_file_read(
            {"path": str(p)},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        # No shell artifacts (exit codes, command echoes, etc.)
        assert result.output == "clean content"
        assert "$" not in result.output
        assert "cat" not in result.output

    async def test_file_write_output_is_structured_message(self, tmp_path) -> None:
        """file_write output is a structured message, not raw shell output."""
        target = tmp_path / "out.txt"
        result = await execute_file_write(
            {"path": str(target), "content": "hello"},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        # Contains meaningful structured info
        assert "5" in result.output  # char count
        assert str(target) in result.output  # path echoed back
        # No shell artifacts
        assert "echo" not in result.output
        assert ">" not in result.output

    async def test_file_read_error_is_structured_not_stderr(self, tmp_path) -> None:
        """Error from file_read is a clean message, not raw stderr."""
        result = await execute_file_read(
            {"path": str(tmp_path / "nope.txt")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert result.error is not None
        # Not raw stderr like "cat: /path: No such file or directory"
        assert "cat:" not in result.error
        assert "No such file" not in result.error

    async def test_file_write_resolves_relative_paths(self, tmp_path) -> None:
        """file_write resolves relative paths against working_dir."""
        result = await execute_file_write(
            {"path": "relative/path/file.txt", "content": "data"},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        expected = tmp_path / "relative" / "path" / "file.txt"
        assert expected.exists()
        assert expected.read_text() == "data"

    async def test_file_read_resolves_relative_paths(self, tmp_path) -> None:
        """file_read resolves relative paths against working_dir."""
        p = tmp_path / "sub" / "file.txt"
        p.parent.mkdir(parents=True)
        p.write_text("found it")
        result = await execute_file_read(
            {"path": "sub/file.txt"},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        assert result.output == "found it"
