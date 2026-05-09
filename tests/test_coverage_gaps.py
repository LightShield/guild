"""Tests to close remaining branch coverage gaps across multiple modules."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ======================================================================
# Shell tool edge cases (shell.py lines 62, 72, 86-87, 112)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestShellEdgeCases:
    """Cover shell tool edge-case branches."""

    async def test_shell_empty_command_returns_error(self) -> None:
        """Empty command string returns an error ToolResult."""
        from guild.tools.shell import execute_shell

        result = await execute_shell({"command": ""}, working_dir="/tmp")
        assert result.success is False
        assert "command" in (result.error or "").lower()

    async def test_shell_non_int_timeout_uses_default(self) -> None:
        """Non-numeric timeout falls back to default."""
        from guild.tools.shell import execute_shell

        result = await execute_shell(
            {"command": "echo hi", "timeout": "not-a-number"},
            working_dir="/tmp",
        )
        assert result.success is True
        assert "hi" in result.output

    async def test_shell_oserror_on_subprocess_creation(self) -> None:
        """OSError during subprocess creation returns a descriptive error."""
        from guild.tools.shell import execute_shell

        with patch("guild.tools.shell.asyncio.create_subprocess_shell", side_effect=OSError("no such shell")):
            result = await execute_shell({"command": "echo test"}, working_dir="/tmp")
        assert result.success is False
        assert "Failed to start" in (result.error or "")

    async def test_shell_stderr_included_in_output(self) -> None:
        """Commands that write to stderr include it in output."""
        from guild.tools.shell import execute_shell

        result = await execute_shell(
            {"command": "echo err >&2"},
            working_dir="/tmp",
        )
        # stderr should be present in output
        assert "[stderr]" in result.output


# ======================================================================
# Memory format_index_for_prompt (memory.py lines 96-100)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-07.6")
class TestMemoryFormatIndex:
    """Tests for MemoryIndex.format_index_for_prompt."""

    def test_format_empty_index_returns_empty(self) -> None:
        """Empty index produces an empty string."""
        from guild.knowledge.memory import MemoryIndex

        # We only need the method, not a full storage connection
        index = MemoryIndex.__new__(MemoryIndex)
        result = index.format_index_for_prompt([])
        assert result == ""

    def test_format_index_with_entries(self) -> None:
        """Non-empty index produces header and bullet list."""
        from guild.knowledge.memory import MemoryIndex

        index = MemoryIndex.__new__(MemoryIndex)
        result = index.format_index_for_prompt(["Entry one", "Entry two"])
        assert "## Agent Memory Index" in result
        assert "- Entry one" in result
        assert "- Entry two" in result


# ======================================================================
# MCP Registry edge cases (registry.py lines 44, 64, 68)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.8")
class TestMCPRegistryEdgeCases:
    """Cover MCP tool registry edge cases."""

    async def test_remove_server_unknown_name_noop(self) -> None:
        """Removing a non-existent server does nothing (no error)."""
        from guild.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry()
        await registry.remove_server("nonexistent")
        # Should not raise

    async def test_call_tool_unknown_tool_raises(self) -> None:
        """Calling an unregistered tool raises KeyError."""
        from guild.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            await registry.call_tool("no-such-tool", {})

    async def test_call_tool_server_disconnected_raises(self) -> None:
        """Calling a tool whose server is gone raises KeyError."""
        from guild.mcp.client import MCPTool
        from guild.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry()
        # Manually inject a tool without a matching client
        registry._tools["orphan-tool"] = MCPTool(
            name="orphan-tool",
            description="test",
            input_schema={},
            server_name="gone-server",
        )
        with pytest.raises(KeyError, match="not connected"):
            await registry.call_tool("orphan-tool", {})


# ======================================================================
# MessageBus receive timeout (bus.py line 55)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.7")
class TestMessageBusTimeout:
    """MessageBus.receive with timeout returns None."""

    async def test_receive_timeout_returns_none(self) -> None:
        """receive() returns None when timeout expires."""
        from guild.orchestration.bus import MessageBus

        bus = MessageBus()
        result = await bus.receive("agent-x", timeout=0.05)
        assert result is None


# ======================================================================
# QuestionQueue get_answer for nonexistent question (queue.py line 95)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-15.1")
class TestQuestionQueueEdgeCases:
    """Edge cases for QuestionQueue."""

    async def test_get_answer_nonexistent_returns_none(self, tmp_path: Path) -> None:
        """get_answer for a nonexistent question returns None."""
        from guild.escalation.queue import QuestionQueue
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        queue = QuestionQueue(store)
        result = await queue.get_answer("totally-fake-id")
        assert result is None
        await store.close()


# ======================================================================
# Notifier unsupported platform (notify.py line 89)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestNotifierUnsupportedPlatform:
    """Desktop notification on unsupported platform."""

    async def test_desktop_notification_unsupported_platform(self) -> None:
        """Desktop notification logs warning on unsupported platforms."""
        from guild.escalation.notify import NotificationChannel, Notifier

        notifier = Notifier(channels=[NotificationChannel.DESKTOP])
        with patch("guild.escalation.notify.sys") as mock_sys:
            mock_sys.platform = "win32"
            with patch("guild.escalation.notify.logger") as mock_logger:
                await notifier.notify("Windows test")
                mock_logger.warning.assert_called_once()
                assert "not supported" in mock_logger.warning.call_args[0][0].lower()


# ======================================================================
# StructuredFormatter with exception (logging_config.py line 27)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-11.3")
class TestStructuredFormatterException:
    """StructuredFormatter formatting with exc_info."""

    def test_format_with_exception(self) -> None:
        """Log records with exc_info include an 'exception' key in output."""
        from guild.observability.logging_config import StructuredFormatter

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


# ======================================================================
# DaemonSupervisor request_shutdown (supervisor.py line 54)
# and signal handler restore branches (78->80, 80->82)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-23.8")
class TestSupervisorEdgeCases:
    """Cover supervisor edge cases."""

    def test_request_shutdown_sets_flag(self, tmp_path: Path) -> None:
        """request_shutdown() directly sets the shutdown flag."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="t1")
        assert sup.shutdown_requested is False
        sup.request_shutdown()
        assert sup.shutdown_requested is True

    def test_restore_signal_handlers_when_none(self, tmp_path: Path) -> None:
        """restore_signal_handlers skips when originals are None."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="t2")
        # Don't install first - _original_sigterm and _original_sigint are None
        # Should not raise
        sup.restore_signal_handlers()

    async def test_remove_pid_file_when_not_exists(self, tmp_path: Path) -> None:
        """remove_pid_file when no PID file does nothing."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="t3")
        # PID file doesn't exist
        sup.remove_pid_file()  # Should not raise


# ======================================================================
# BackpressureManager release when _active is 0 (ratelimit.py 45->47)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-20.3")
class TestBackpressureReleaseBranch:
    """BackpressureManager release edge case."""

    async def test_release_when_active_is_zero(self) -> None:
        """Releasing when active==0 still releases semaphore without decrement."""
        from guild.agent.ratelimit import BackpressureManager

        mgr = BackpressureManager(max_concurrent=2)
        # Don't acquire first, just release — _active stays at 0
        mgr.release()
        # active should still be 0
        assert mgr._active == 0


# ======================================================================
# RollbackContext — rollback file that didn't exist and then appeared
# (rollback.py 53->61)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-06.11")
class TestRollbackDeletesCreatedFile:
    """Rollback deletes files that were created after capture."""

    def test_rollback_deletes_file_created_after_capture(self, tmp_path: Path) -> None:
        """If a file didn't exist at capture time but exists now, rollback deletes it."""
        from guild.agent.rollback import RollbackContext

        new_file = tmp_path / "new.txt"
        ctx = RollbackContext()
        ctx.capture(str(new_file))

        # Create the file after capture
        new_file.write_text("created content")
        assert new_file.exists()

        # Rollback should delete it
        rolled = ctx.rollback()
        assert str(new_file) in rolled
        assert not new_file.exists()


# ======================================================================
# Block Registry validation edge cases (registry.py)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.21")
class TestRegistryValidationEdgeCases:
    """Cover remaining validation edge cases in BlockRegistry."""

    def test_empty_entry_block_error(self) -> None:
        """Team with empty entry_block produces validation error."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="no-entry",
            blocks={"code": "coder"},
            connections=[],
            entry_block="",
        )
        errors = registry.validate_team(team)
        assert any("entry_block" in e.lower() for e in errors)

    def test_entry_block_not_in_team_error(self) -> None:
        """Team with entry_block not in blocks dict produces validation error."""
        from guild.blocks import BlockRegistry, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-entry",
            blocks={"code": "coder"},
            connections=[],
            entry_block="missing",
        )
        errors = registry.validate_team(team)
        assert any("missing" in e and "not in team" in e for e in errors)

    def test_unregistered_block_type_error(self) -> None:
        """Team referencing an unknown block type produces validation error."""
        from guild.blocks import BlockRegistry, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="unknown-type",
            blocks={"x": "nonexistent_block_type"},
            connections=[],
            entry_block="x",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_block_type" in e and "not found" in e for e in errors)

    def test_connection_source_not_in_team(self) -> None:
        """Connection referencing a source block not in team produces error."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-conn-src",
            blocks={"code": "coder"},
            connections=[
                Connection(
                    source_block="ghost",
                    source_port="plan",
                    target_block="code",
                    target_port="spec",
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("ghost" in e and "source" in e.lower() for e in errors)

    def test_connection_target_not_in_team(self) -> None:
        """Connection referencing a target block not in team produces error."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-conn-tgt",
            blocks={"plan": "planner"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="plan",
                    target_block="ghost",
                    target_port="spec",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("ghost" in e and "target" in e.lower() for e in errors)

    def test_connection_with_unregistered_block_types(self) -> None:
        """Connection where block type not in registry returns early."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="unregistered-types",
            blocks={"a": "fake_type_a", "b": "fake_type_b"},
            connections=[
                Connection(
                    source_block="a",
                    source_port="out",
                    target_block="b",
                    target_port="in",
                ),
            ],
            entry_block="a",
        )
        errors = registry.validate_team(team)
        # Should get "not found in registry" errors for both blocks
        assert any("fake_type_a" in e for e in errors)

    def test_invalid_output_port_name_error(self) -> None:
        """Connection referencing nonexistent output port produces error."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-port",
            blocks={"plan": "planner", "code": "coder"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="nonexistent_output",
                    target_block="code",
                    target_port="spec",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_output" in e and "not found" in e for e in errors)

    def test_invalid_input_port_name_error(self) -> None:
        """Connection referencing nonexistent input port produces error."""
        from guild.blocks import BlockRegistry, Connection, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-input-port",
            blocks={"plan": "planner", "code": "coder"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="plan",
                    target_block="code",
                    target_port="nonexistent_input",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_input" in e and "not found" in e for e in errors)

    def test_load_from_nonexistent_dir_returns_zero(self) -> None:
        """Loading from a non-directory path returns 0."""
        from guild.blocks import BlockRegistry

        registry = BlockRegistry()
        count = registry.load_from_dir(Path("/nonexistent/path"))
        assert count == 0

    def test_load_from_dir_bad_toml_logs_error(self, tmp_path: Path) -> None:
        """Invalid TOML file is gracefully skipped."""
        from guild.blocks import BlockRegistry

        blocks_dir = tmp_path / "blocks"
        blocks_dir.mkdir()
        (blocks_dir / "bad.toml").write_text("this is [not valid toml")

        registry = BlockRegistry()
        count = registry.load_from_dir(blocks_dir)
        assert count == 0

    def test_list_teams_returns_registered_teams(self) -> None:
        """list_teams returns all registered team definitions."""
        from guild.blocks import BlockRegistry, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="test-team",
            blocks={"code": "coder"},
            connections=[],
            entry_block="code",
        )
        registry.register_team(team)
        teams = registry.list_teams()
        assert len(teams) >= 1
        assert any(t.name == "test-team" for t in teams)

    def test_loop_max_iterations_less_than_1_error(self) -> None:
        """Loop with max_iterations < 1 produces validation error."""
        from guild.blocks import BlockRegistry, LoopDef, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="bad-loop-iters",
            blocks={"code": "coder", "eval": "evaluator"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="code",
                    evaluator_block="eval",
                    max_iterations=0,
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("max_iterations" in e for e in errors)

    def test_loop_evaluator_not_in_team(self) -> None:
        """Loop referencing non-existent evaluator produces error."""
        from guild.blocks import BlockRegistry, LoopDef, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="loop-no-eval",
            blocks={"code": "coder"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="code",
                    evaluator_block="ghost_evaluator",
                    max_iterations=3,
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("ghost_evaluator" in e for e in errors)


# ======================================================================
# Port types: get_composite_ports when block is None (port_types.py line 134)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.33")
class TestCompositePortsUnknownBlock:
    """get_composite_ports skips blocks unknown to registry."""

    def test_composite_ports_with_unknown_block_type(self) -> None:
        """Unknown block types are skipped gracefully."""
        from guild.blocks.definition import TeamDef
        from guild.blocks.port_types import get_composite_ports
        from guild.blocks.registry import BlockRegistry

        registry = BlockRegistry()
        team = TeamDef(
            name="partial-team",
            blocks={"known": "coder", "unknown": "not_registered_type"},
            connections=[],
            entry_block="known",
        )
        inputs, outputs = get_composite_ports(team, registry)
        # Should still get ports from the known block (coder)
        input_names = [p.name for p in inputs]
        assert "spec" in input_names or "context" in input_names


# ======================================================================
# Search tool edge cases (search.py lines 46, 52, 85-86, 114-115, 131-132, 147, 153)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestSearchToolEdgeCases:
    """Cover search/glob tool edge cases."""

    async def test_search_empty_pattern_returns_error(self) -> None:
        """Missing pattern returns error."""
        from guild.tools.search import execute_search

        result = await execute_search({"pattern": ""}, working_dir="/tmp")
        assert result.success is False
        assert "pattern" in (result.error or "").lower()

    async def test_search_path_not_found(self, tmp_path: Path) -> None:
        """Non-existent path returns error."""
        from guild.tools.search import execute_search

        result = await execute_search(
            {"pattern": "hello", "path": str(tmp_path / "nope")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_search_single_file(self, tmp_path: Path) -> None:
        """Search on a single file works."""
        from guild.tools.search import execute_search

        f = tmp_path / "test.txt"
        f.write_text("hello world\ngoodbye world\n")
        result = await execute_search(
            {"pattern": "hello", "path": str(f)},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        assert "hello" in result.output

    async def test_search_file_oserror_skipped(self, tmp_path: Path) -> None:
        """Files that raise OSError on read are silently skipped."""
        from guild.tools.search import execute_search

        f = tmp_path / "test.txt"
        f.write_text("content")
        # Make file unreadable
        f.chmod(0o000)
        try:
            result = await execute_search(
                {"pattern": "content", "path": str(tmp_path)},
                working_dir=str(tmp_path),
            )
            # Should not error out, just find no matches
            assert result.success is True
        finally:
            f.chmod(0o644)

    async def test_search_is_relative_to_false(self, tmp_path: Path) -> None:
        """File not relative to base uses absolute path in results."""
        from guild.tools.search import _is_relative_to

        assert _is_relative_to(Path("/a/b/c"), Path("/a/b")) is True
        assert _is_relative_to(Path("/x/y"), Path("/a/b")) is False

    async def test_glob_empty_pattern_returns_error(self) -> None:
        """Missing glob pattern returns error."""
        from guild.tools.search import execute_glob

        result = await execute_glob({"pattern": ""}, working_dir="/tmp")
        assert result.success is False
        assert "pattern" in (result.error or "").lower()

    async def test_glob_path_not_found(self, tmp_path: Path) -> None:
        """Non-existent path returns error."""
        from guild.tools.search import execute_glob

        result = await execute_glob(
            {"pattern": "*.txt", "path": str(tmp_path / "nope")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()


# ======================================================================
# Plugin loader edge cases (plugin.py lines 100-101, 134-135, 146-147, 152-153, 177, 199)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.9")
class TestPluginLoaderEdgeCases:
    """Cover plugin loader edge cases."""

    def test_discover_skips_non_directory(self, tmp_path: Path) -> None:
        """discover() skips paths that aren't directories."""
        from guild.tools.plugin import PluginLoader

        fake_path = tmp_path / "not-a-dir"
        loader = PluginLoader(plugin_dirs=[fake_path])
        plugins = loader.discover()
        assert plugins == []

    def test_load_from_file_invalid_toml(self, tmp_path: Path) -> None:
        """load_from_file returns None for invalid TOML."""
        from guild.tools.plugin import PluginLoader

        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("this is not valid toml [[[")
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(bad_file)
        assert result is None

    def test_load_from_file_no_tool_section(self, tmp_path: Path) -> None:
        """load_from_file returns None when [tool] section missing."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "no_tool.toml"
        f.write_text('[other]\nkey = "value"\n')
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(f)
        assert result is None

    def test_load_from_file_no_tool_name(self, tmp_path: Path) -> None:
        """load_from_file returns None when tool.name is missing."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "no_name.toml"
        f.write_text('[tool]\ndescription = "no name"\n')
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(f)
        assert result is None

    def test_load_from_dir_nonexistent(self, tmp_path: Path) -> None:
        """load_from_dir returns empty for non-directory."""
        from guild.tools.plugin import PluginLoader

        loader = PluginLoader(plugin_dirs=[tmp_path / "nope"])
        result = loader.load_from_dir(tmp_path / "nope")
        assert result == []

    def test_cache_update_existing_key(self) -> None:
        """ToolCache.put updates an existing key and moves to end."""
        from guild.tools.base import ToolResult
        from guild.tools.plugin import ToolCache

        cache = ToolCache(max_size=5)
        r1 = ToolResult(success=True, output="first")
        r2 = ToolResult(success=True, output="second")
        cache.put("key1", r1)
        cache.put("key1", r2)  # Update existing
        result = cache.get("key1")
        assert result is not None
        assert result.output == "second"

    def test_cache_evicts_oldest_when_full(self) -> None:
        """ToolCache evicts oldest entries when at capacity."""
        from guild.tools.base import ToolResult
        from guild.tools.plugin import ToolCache

        cache = ToolCache(max_size=2)
        cache.put("k1", ToolResult(success=True, output="1"))
        cache.put("k2", ToolResult(success=True, output="2"))
        cache.put("k3", ToolResult(success=True, output="3"))
        # k1 should be evicted
        assert cache.get("k1") is None
        assert cache.get("k2") is not None
        assert cache.get("k3") is not None

    def test_parse_parameters_with_required_dict(self, tmp_path: Path) -> None:
        """Parser handles required as a dict with 'list' key."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "tool.toml"
        f.write_text(
            '[tool]\n'
            'name = "my-tool"\n'
            'description = "Test tool"\n'
            '\n'
            '[tool.parameters]\n'
            'type = "object"\n'
            '\n'
            '[tool.parameters.properties.arg1]\n'
            'type = "string"\n'
            '\n'
            '[tool.parameters.required]\n'
            'list = ["arg1"]\n'
        )
        loader = PluginLoader(plugin_dirs=[tmp_path])
        plugin = loader.load_from_file(f)
        assert plugin is not None
        assert plugin.parameters.get("required") == ["arg1"]


# ======================================================================
# Temporal knowledge edge cases (temporal.py lines 68-69, 78, 125, 149, 165-167)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-27")
class TestTemporalKnowledgeEdgeCases:
    """Cover temporal knowledge assembly edge cases."""

    async def test_get_relevant_context_no_instructions(self, tmp_path: Path) -> None:
        """get_relevant_context works when no prompt.md exists."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_relevant_context("test task")
        # No instructions, no decisions, no learnings => empty string
        assert result == ""
        await store.close()

    async def test_get_relevant_context_with_instructions(self, tmp_path: Path) -> None:
        """get_relevant_context includes prompt.md content."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "prompt.md").write_text("# Custom Instructions\nDo X.")

        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_relevant_context("test task")
        assert "Project Instructions" in result
        assert "Custom Instructions" in result
        await store.close()

    async def test_get_present_state_with_git(self, tmp_path: Path) -> None:
        """get_present_state runs git commands successfully."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        # Use the actual guild repo as working_dir
        result = await tk.get_present_state("/Users/ormagen/workspace/private/guild")
        assert "Present State" in result
        await store.close()

    async def test_get_present_state_nonexistent_dir(self, tmp_path: Path) -> None:
        """get_present_state handles failure gracefully when commands fail."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_present_state("/nonexistent/path/xyz")
        assert "No project state" in result
        await store.close()

    async def test_get_key_past_info_empty(self, tmp_path: Path) -> None:
        """get_key_past_info returns empty when no data."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        store = Storage(tmp_path / "test.db")
        await store.connect()
        tk = TemporalKnowledge(guild_dir=guild_dir, storage=store)
        result = await tk.get_key_past_info("test task")
        assert result == ""
        await store.close()


# ======================================================================
# Offline manager connectivity branch (offline/manager.py 45->exit)
# ======================================================================


@pytest.mark.unit
class TestOfflineManagerEdgeCases:
    """Offline manager check_connectivity exception path."""

    async def test_connectivity_exception_sets_offline(self) -> None:
        """If health_check raises, is_online is set to False."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check.side_effect = RuntimeError("connection refused")
        mgr = OfflineManager(provider=provider)
        result = await mgr.check_connectivity()
        assert result is False
        assert mgr.is_online is False


# ======================================================================
# Resource monitor stealth mode (resource.py 149->exit)
# ======================================================================


@pytest.mark.unit
class TestResourceMonitorStealthExit:
    """ResourceMonitor stealth mode exits when user becomes idle."""

    async def test_stealth_mode_exits_on_idle(self) -> None:
        """Stealth mode blocks while active and unblocks when idle."""
        from guild.daemon.resource import ActivityState, ResourceMonitor, SchedulingMode

        call_count = 0

        def detector() -> ActivityState:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return ActivityState.ACTIVE
            return ActivityState.IDLE

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=detector,
            cpu_reader=lambda: 20.0,
        )
        monitor.thresholds.poll_interval_seconds = 0.01
        await monitor.wait_if_throttled()
        # Should have polled at least twice (once ACTIVE, once IDLE)
        assert call_count >= 2


# ======================================================================
# Notify loop-continue branch (notify.py 59->52)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-15.5")
class TestNotifierLoopContinue:
    """NONE channel causes a continue without action."""

    async def test_none_channel_mixed_with_bell(self) -> None:
        """NONE channel is skipped, bell channel still fires."""
        from guild.escalation.notify import NotificationChannel, Notifier

        notifier = Notifier(
            channels=[NotificationChannel.NONE, NotificationChannel.TERMINAL_BELL]
        )
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify("Test")
            mock_stdout.write.assert_called_once_with("\a")
