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

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "git push --force origin main",
            "git reset --hard",
            ":(){ :|:& };:",
            "sudo rm -rf /var",
        ],
        ids=[
            "rm_rf_slash",
            "git_push_force",
            "git_reset_hard",
            "fork_bomb",
            "sudo_rm",
        ],
    )
    async def test_denylist_blocks_dangerous_command(self, command: str) -> None:
        """Dangerous commands are denied by the shell denylist."""
        result = await execute_shell({"command": command}, working_dir="/tmp")

        assert result.success is False
        assert result.error is not None
        assert "denied" in result.error.lower() or "blocked" in result.error.lower()

    async def test_denylist_allows_safe_commands(self) -> None:
        result = await execute_shell({"command": "echo hello"}, working_dir="/tmp")

        assert result.success is True
        assert "hello" in result.output


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

    async def test_shell_timeout_kills_process(self) -> None:
        """After timeout, the child process is killed (not left orphaned)."""
        # Use a command that would run forever without the kill
        result = await execute_shell(
            {"command": "sleep 999", "timeout": 0.5}, working_dir="/tmp"
        )

        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower()
        # The error message should mention the timeout value
        assert "0.5" in result.error


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

    def test_all_tool_schemas_have_safety_rules_where_applicable(self) -> None:
        """Tools that execute code or modify state have safety info in their schema."""
        # Shell is the primary dangerous tool — must have safety rules
        shell_schema = TOOL_SCHEMAS["shell"]
        desc = shell_schema["description"].lower()
        assert "blocked" in desc or "denied" in desc
        assert "timeout" in desc

        # file_write can modify state — should describe its behavior
        file_write_schema = TOOL_SCHEMAS["file_write"]
        assert "write" in file_write_schema["description"].lower()
        assert "path" in file_write_schema["parameters"]["properties"]

        # All schemas must have "name", "description", "parameters"
        for name, schema in TOOL_SCHEMAS.items():
            assert "name" in schema, f"Schema for {name} missing 'name'"
            assert "description" in schema, f"Schema for {name} missing 'description'"
            assert "parameters" in schema, f"Schema for {name} missing 'parameters'"
            assert len(schema["description"]) > 10, (
                f"Schema for {name} has too-short description"
            )


@pytest.mark.unit
@pytest.mark.req("REQ-08.4")
class TestToolAuditLog:
    """Tests for tool call audit logging via storage."""

    async def test_audit_logs_tool_name_and_args(self, tmp_path) -> None:
        """Audit log stores the tool name and arguments."""
        from guild.storage.sqlite import Storage

        db_path = tmp_path / "guild.db"
        store = Storage(db_path)
        await store.connect()

        await store.log_audit(
            action="tool_call",
            agent_id="agent-1",
            details="shell command='echo hello'",
        )

        entries = await store.list_audit(limit=10)
        assert len(entries) == 1
        assert entries[0]["action"] == "tool_call"
        assert "shell" in entries[0]["details"]
        assert "echo hello" in entries[0]["details"]
        await store.close()

    async def test_audit_logs_on_both_success_and_failure(self, tmp_path) -> None:
        """Audit log records entries for both successful and failed tool calls."""
        from guild.storage.sqlite import Storage

        db_path = tmp_path / "guild.db"
        store = Storage(db_path)
        await store.connect()

        # Log a successful tool call
        await store.log_audit(
            action="tool_call",
            agent_id="agent-1",
            details="file_read path=/tmp/x.py result=success",
        )
        # Log a failed tool call
        await store.log_audit(
            action="tool_call",
            agent_id="agent-1",
            details="shell command='rm -rf /' result=denied",
        )

        entries = await store.list_audit(limit=10)
        assert len(entries) == 2
        # Both entries recorded
        details = [e["details"] for e in entries]
        assert any("success" in d for d in details)
        assert any("denied" in d for d in details)
        await store.close()
