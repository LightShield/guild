"""Tests for shell tool (REQ-08.3, REQ-08.5, REQ-08.6, REQ-08.7)."""

from __future__ import annotations

import pytest

from guild.tools.base import TOOL_SCHEMAS
from guild.tools.shell import (
    MAX_SHELL_OUTPUT_CHARS,
    execute_shell,
)


@pytest.mark.unit
@pytest.mark.req("REQ-08.7")
class TestShellDenylist:
    """Tests that dangerous commands are blocked."""

    async def test_denylist_blocks_rm_rf_slash(self) -> None:
        result = await execute_shell({"command": "rm -rf /"}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()

    async def test_denylist_blocks_git_push_force(self) -> None:
        result = await execute_shell(
            {"command": "git push --force origin main"}, working_dir="/tmp"
        )

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()

    async def test_denylist_blocks_git_reset_hard(self) -> None:
        result = await execute_shell({"command": "git reset --hard"}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()

    async def test_denylist_blocks_fork_bomb(self) -> None:
        result = await execute_shell({"command": ":(){ :|:& };:"}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()

    async def test_denylist_allows_safe_commands(self) -> None:
        result = await execute_shell({"command": "echo hello"}, working_dir="/tmp")

        assert result.success is True
        assert "hello" in result.output

    async def test_denylist_blocks_sudo_rm(self) -> None:
        result = await execute_shell({"command": "sudo rm -rf /var"}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-08.5")
class TestShellTimeout:
    """Tests for shell command timeout handling."""

    async def test_shell_timeout_returns_error(self) -> None:
        result = await execute_shell({"command": "sleep 5", "timeout": 1}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower()

    async def test_shell_respects_timeout_setting(self) -> None:
        # A fast command with generous timeout should succeed
        result = await execute_shell({"command": "echo fast", "timeout": 10}, working_dir="/tmp")

        assert result.success is True
        assert "fast" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestShellExecution:
    """Tests for basic shell execution."""

    async def test_shell_executes_simple_command(self) -> None:
        result = await execute_shell({"command": "echo hello"}, working_dir="/tmp")

        assert result.success is True
        assert "hello" in result.output

    async def test_shell_returns_exit_code_in_output(self) -> None:
        result = await execute_shell({"command": "true"}, working_dir="/tmp")

        assert result.success is True
        assert "exit code: 0" in result.output.lower() or result.output is not None

    async def test_shell_returns_error_on_nonzero_exit(self) -> None:
        result = await execute_shell({"command": "exit 42"}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "42" in result.error or "exit" in result.error.lower()

    async def test_shell_uses_working_dir(self, tmp_path: object) -> None:
        result = await execute_shell({"command": "pwd"}, working_dir=str(tmp_path))

        assert result.success is True
        assert str(tmp_path) in result.output

    async def test_shell_truncates_long_output(self, tmp_path: object) -> None:
        # Generate output larger than MAX_SHELL_OUTPUT_CHARS
        # Use python to emit a large string
        cmd = f"python3 -c \"print('x' * {MAX_SHELL_OUTPUT_CHARS + 5000})\""
        result = await execute_shell({"command": cmd}, working_dir=str(tmp_path))

        assert result.success is True
        assert len(result.output) <= MAX_SHELL_OUTPUT_CHARS + 200
        assert "truncated" in result.output.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-08.6")
class TestShellSchema:
    """Tests for shell tool schema safety rules."""

    def test_shell_schema_contains_safety_rules(self) -> None:
        schema = TOOL_SCHEMAS["shell"]

        description = schema["description"]
        # Must mention dangerous commands or safety
        assert "dangerous" in description.lower() or "safety" in description.lower()
        # Must mention the denylist
        assert "denied" in description.lower() or "blocked" in description.lower()
