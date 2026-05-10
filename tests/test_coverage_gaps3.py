"""Third batch of tests to close remaining branch coverage gaps."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ======================================================================
# Lifecycle pause/resume/complete edge cases (lifecycle.py 110-111, 132-133, 235-236)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-25")
class TestLifecycleEdgeCases:
    """Cover lifecycle manager edge cases."""

    async def test_pause_task_not_found(self, tmp_path: Path) -> None:
        """pause_task returns False when task doesn't exist."""
        from guild.daemon.lifecycle import LifecycleManager
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.pause_task("nonexistent")
        assert result is False
        await store.close()

    async def test_resume_task_not_found(self, tmp_path: Path) -> None:
        """resume_task returns False when task doesn't exist."""
        from guild.daemon.lifecycle import LifecycleManager
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.resume_task("nonexistent")
        assert result is False
        await store.close()

    async def test_pause_task_wrong_status(self, tmp_path: Path) -> None:
        """pause_task returns False when task is not 'running'."""
        from guild.daemon.lifecycle import LifecycleManager
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        # Create a task then set it to 'completed'
        await store.create_task(task_id="t1", description="test")
        await store.update_task("t1", status="completed")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.pause_task("t1")
        assert result is False
        await store.close()

    async def test_resume_task_wrong_status(self, tmp_path: Path) -> None:
        """resume_task returns False when task is not 'paused'."""
        from guild.daemon.lifecycle import LifecycleManager
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task(task_id="t1", description="test")
        await store.update_task("t1", status="running")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        mgr = LifecycleManager(run_dir=run_dir, storage=store)
        result = await mgr.resume_task("t1")
        assert result is False
        await store.close()

    async def test_task_queue_complete(self, tmp_path: Path) -> None:
        """complete() removes task from active list."""
        from guild.daemon.lifecycle import TaskQueue

        queue = TaskQueue(max_concurrent=2)
        await queue.enqueue("t1")
        task_id = await queue.dequeue()
        assert task_id == "t1"
        assert queue.active_count == 1
        queue.complete("t1")
        assert queue.active_count == 0

    async def test_task_queue_complete_unknown_task(self, tmp_path: Path) -> None:
        """complete() with unknown task_id does nothing."""
        from guild.daemon.lifecycle import TaskQueue

        queue = TaskQueue(max_concurrent=2)
        queue.complete("unknown")
        assert queue.active_count == 0


# ======================================================================
# Config loader: _write_toml_bytes, _toml_literal, merge+cleanup (loader.py)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestConfigLoaderInternals:
    """Cover config loader internal functions."""

    def test_write_toml_bytes(self) -> None:
        """_write_toml_bytes writes correct TOML bytes."""
        from guild.config.loader import _write_toml_bytes

        buf = io.BytesIO()
        data = {
            "model": "test-model",
            "debug": True,
            "provider": {"base_url": "http://localhost:11434"},
        }
        _write_toml_bytes(buf, data)
        content = buf.getvalue().decode()
        assert 'model = "test-model"' in content
        assert "debug = true" in content
        assert "[provider]" in content
        assert 'base_url = "http://localhost:11434"' in content

    def test_toml_literal_bool_false(self) -> None:
        """_toml_literal formats False as 'false'."""
        from guild.config.loader import _toml_literal

        assert _toml_literal(False) == "false"
        assert _toml_literal(True) == "true"

    def test_toml_literal_int(self) -> None:
        """_toml_literal formats integers correctly."""
        from guild.config.loader import _toml_literal

        assert _toml_literal(42) == "42"

    def test_merge_toml_files_both_present(self, tmp_path: Path) -> None:
        """When both global and project config exist, they are merged."""
        from guild.config.loader import _merge_toml_files

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        project_config = guild_dir / "config.toml"
        project_config.write_text('model = "project-model"\n')

        # Patch global path to avoid depending on actual ~/.guild
        with patch("guild.config.loader.Path.home", return_value=tmp_path / "home"):
            home_guild = tmp_path / "home" / ".guild"
            home_guild.mkdir(parents=True)
            (home_guild / "config.toml").write_text('model = "global-model"\ndebug = true\n')

            result = _merge_toml_files(guild_dir)
            # Result should be a temp file with merged content
            assert result is not None
            content = result.read_text()
            # Project overrides global for model
            assert "project-model" in content
            # Cleanup
            result.unlink()

    def test_load_config_no_guild_dir(self) -> None:
        """load_config works without a guild_dir (uses defaults)."""
        from guild.config.loader import load_config

        # With no guild_dir and no global config, should return default config
        with patch("guild.config.loader.Path.home", return_value=Path("/nonexistent")):
            config = load_config(guild_dir=None)
            # Should still produce a valid config with defaults
            assert config is not None


# ======================================================================
# Worktree _parse_worktree_list (worktree.py lines 137->146, 152->162)
# ======================================================================


@pytest.mark.unit
class TestWorktreeParseList:
    """Cover worktree list parsing edge cases."""

    def test_parse_empty_output(self) -> None:
        """Empty output produces empty list."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=Path("/tmp"))
        result = mgr._parse_worktree_list("")
        assert result == []

    def test_parse_guild_worktrees(self) -> None:
        """Parses guild-managed worktrees from porcelain output."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=Path("/tmp"))
        output = (
            "worktree /repo\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /repo/.guild/worktrees/task-1\n"
            "branch refs/heads/guild/task-1\n"
            "\n"
        )
        result = mgr._parse_worktree_list(output)
        assert len(result) == 1
        assert result[0].task_id == "task-1"
        assert result[0].branch == "guild/task-1"

    def test_parse_skips_staging(self) -> None:
        """Staging worktree is not included in results."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=Path("/tmp"))
        output = (
            "worktree /repo/.guild/worktrees/_staging\n" "branch refs/heads/guild/staging\n" "\n"
        )
        result = mgr._parse_worktree_list(output)
        assert result == []

    def test_parse_no_trailing_newline(self) -> None:
        """Handles last entry without trailing blank line."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=Path("/tmp"))
        # No blank line after last entry
        output = "worktree /repo/.guild/worktrees/task-2\n" "branch refs/heads/guild/task-2\n"
        result = mgr._parse_worktree_list(output)
        assert len(result) == 1
        assert result[0].task_id == "task-2"

    def test_parse_non_guild_branches_excluded(self) -> None:
        """Non-guild branches are excluded from results."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=Path("/tmp"))
        output = "worktree /repo\n" "branch refs/heads/feature/my-feature\n" "\n"
        result = mgr._parse_worktree_list(output)
        assert result == []


# ======================================================================
# MCP Client edge cases (client.py 58, 77, 108, 123, 127)
# ======================================================================


@pytest.mark.unit
class TestMCPClientEdgeCases:
    """Cover MCP client edge cases."""

    async def test_disconnect_when_not_connected(self) -> None:
        """disconnect() is a no-op when not connected."""
        from guild.mcp.client import MCPClient, MCPServerConfig

        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        # Should not raise
        await client.disconnect()

    async def test_send_request_not_connected_raises(self) -> None:
        """_send_request raises MCPError when not connected."""
        from guild.mcp.client import MCPClient, MCPError, MCPServerConfig

        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        with pytest.raises(MCPError, match="Not connected"):
            await client._send_request("test/method", {})

    def test_config_property(self) -> None:
        """config property returns the server config."""
        from guild.mcp.client import MCPClient, MCPServerConfig

        config = MCPServerConfig(name="my-server", command="node", args=["mcp.js"])
        client = MCPClient(config)
        assert client.config.name == "my-server"


# ======================================================================
# Daemon sleep_wake edge cases (sleep_wake.py 90, 116-117, 138)
# ======================================================================


@pytest.mark.unit
class TestSleepWakeEdgeCases:
    """Cover sleep/wake detector edge cases."""

    def test_detect_sleep_no_drift(self) -> None:
        """No time drift means no sleep detected."""
        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=5.0),
        )
        # Record current time, then check immediately — no drift
        detector.mark_turn_start()
        slept = detector.check_for_sleep()
        assert slept is False

    def test_detect_sleep_with_drift(self) -> None:
        """Time drift above threshold triggers sleep detection."""
        import time

        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=0.01),
        )
        # Simulate time drift by manually setting last turn time in the past
        detector._last_turn_time = time.monotonic() - 10.0
        slept = detector.check_for_sleep()
        assert slept is True
        assert detector.sleep_detected is True

    def test_clear_sleep_flag(self) -> None:
        """clear_sleep_flag resets the detected state."""
        import time

        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(sleep_threshold_seconds=0.01),
        )
        detector._last_turn_time = time.monotonic() - 10.0
        detector.check_for_sleep()
        assert detector.sleep_detected is True
        detector.clear_sleep_flag()
        assert detector.sleep_detected is False

    async def test_wait_for_provider_recovery_fails(self) -> None:
        """wait_for_provider_recovery returns False after max retries."""
        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False
        result = await detector.wait_for_provider_recovery(provider, max_retries=2)
        assert result is False

    async def test_retry_after_sleep_connection_error(self) -> None:
        """retry_after_sleep catches ConnectionError and retries after recovery."""
        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01),
        )
        provider = AsyncMock()
        provider.health_check.return_value = True

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("lost connection")
            return "success"

        result = await detector.retry_after_sleep(provider, operation)
        assert result == "success"
        assert call_count == 2

    async def test_retry_after_sleep_recovery_fails_reraises(self) -> None:
        """retry_after_sleep re-raises if recovery fails."""
        from guild.daemon.sleep_wake import SleepWakeConfig, SleepWakeDetector

        detector = SleepWakeDetector(
            config=SleepWakeConfig(health_check_retry_delay=0.01, health_check_retries=1),
        )
        provider = AsyncMock()
        provider.health_check.return_value = False

        async def failing_op():
            raise ConnectionError("permanent failure")

        with pytest.raises(ConnectionError, match="permanent failure"):
            await detector.retry_after_sleep(provider, failing_op)


# ======================================================================
# Observability replay edge cases (replay.py 98->exit, 102->99, 104-105)
# ======================================================================


@pytest.mark.unit
class TestReplayEdgeCases:
    """Cover session replay edge cases."""

    async def test_replay_empty_session(self, tmp_path: Path) -> None:
        """Replaying a session with no messages returns empty."""
        from guild.observability.replay import SessionReplay
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        replay = SessionReplay(store)
        messages = await replay.get_session("nonexistent-agent")
        assert messages == []
        await store.close()

    async def test_get_session_summary_empty(self, tmp_path: Path) -> None:
        """Summarizing a session with no messages returns zero counts."""
        from guild.observability.replay import SessionReplay
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        replay = SessionReplay(store)
        summary = await replay.get_session_summary("nonexistent-agent")
        assert summary["turn_count"] == 0
        assert summary["message_count"] == 0
        await store.close()

    def test_format_for_display_empty(self) -> None:
        """format_for_display returns placeholder for empty session."""
        from unittest.mock import MagicMock

        from guild.observability.replay import SessionReplay

        replay = SessionReplay(MagicMock())
        result = replay.format_for_display([])
        assert "empty" in result.lower()

    def test_extract_tool_names_invalid_json(self) -> None:
        """_extract_tool_names handles invalid JSON gracefully."""
        from guild.observability.replay import SessionReplay

        tools: list[str] = []
        SessionReplay._extract_tool_names("not-json", tools)
        assert tools == []

    def test_extract_tool_names_valid(self) -> None:
        """_extract_tool_names extracts tool names from valid JSON."""
        import json

        from guild.observability.replay import SessionReplay

        tools: list[str] = []
        calls = json.dumps(
            [
                {"function": {"name": "shell"}},
                {"function": {"name": "file_read"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        assert "shell" in tools
        assert "file_read" in tools


# ======================================================================
# Worktree create/remove/list error paths (worktree.py 59, 77, 87, 189, 197, 203)
# ======================================================================


@pytest.mark.unit
class TestWorktreeOperations:
    """Test worktree operations with mocked git."""

    async def test_create_fails_raises(self, tmp_path: Path) -> None:
        """create() raises RuntimeError when git fails."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=tmp_path)
        with (
            patch.object(mgr, "_run_git", return_value=(1, "fatal: error")),
            pytest.raises(RuntimeError, match="Failed to create"),
        ):
            await mgr.create("task-1")

    async def test_remove_fails_raises(self, tmp_path: Path) -> None:
        """remove() raises RuntimeError when git fails."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=tmp_path)
        with (
            patch.object(mgr, "_run_git", return_value=(1, "fatal: error")),
            pytest.raises(RuntimeError, match="Failed to remove"),
        ):
            await mgr.remove("task-1")

    async def test_list_active_on_git_failure(self, tmp_path: Path) -> None:
        """list_active() returns empty list when git fails."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=tmp_path)
        with patch.object(mgr, "_run_git", return_value=(1, "error")):
            result = await mgr.list_active()
            assert result == []

    async def test_ensure_staging_existing_path(self, tmp_path: Path) -> None:
        """_ensure_staging_branch returns early if staging path exists."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=tmp_path)
        staging_path = mgr.worktrees_dir / "_staging"
        staging_path.mkdir(parents=True)
        # Should return without calling git
        with patch.object(mgr, "_run_git") as mock_git:
            await mgr._ensure_staging_branch("guild/staging")
            mock_git.assert_not_called()

    async def test_staging_worktree_path_creates_if_missing(self, tmp_path: Path) -> None:
        """_staging_worktree_path calls _ensure_staging_branch when missing."""
        from guild.git.worktree import WorktreeManager

        mgr = WorktreeManager(repo_root=tmp_path)
        with patch.object(mgr, "_ensure_staging_branch", new_callable=AsyncMock) as mock_ensure:
            await mgr._staging_worktree_path("guild/staging")
            mock_ensure.assert_called_once()


# ======================================================================
# MCP Client stdout/readline paths (client.py 123, 127)
# ======================================================================


@pytest.mark.unit
class TestMCPClientProtocol:
    """Test MCP client protocol edge cases."""

    async def test_send_request_stdout_none_raises(self) -> None:
        """_send_request raises MCPError if stdout is None."""
        from guild.mcp.client import MCPClient, MCPError, MCPServerConfig

        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        # Simulate connected but with stdout=None
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = None
        client._process = mock_proc

        with pytest.raises(MCPError, match="stdout"):
            await client._send_request("test", {})

    async def test_send_request_empty_response_raises(self) -> None:
        """_send_request raises MCPError when server closes connection."""
        from guild.mcp.client import MCPClient, MCPError, MCPServerConfig

        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")
        client._process = mock_proc

        with pytest.raises(MCPError, match="closed connection"):
            await client._send_request("test", {})


# ======================================================================
# MessageBus receive without timeout (bus.py line 55)
# ======================================================================


@pytest.mark.unit
class TestBusReceiveNoTimeout:
    """Test bus receive without timeout (blocking)."""

    async def test_receive_without_timeout_gets_message(self) -> None:
        """receive() without timeout returns message immediately if available."""

        from guild.orchestration.bus import MessageBus

        bus = MessageBus()
        # Send first, then receive without timeout
        await bus.send("sender", "receiver", "data", {"hello": "world"})
        msg = await bus.receive("receiver", timeout=None)
        assert msg is not None
        assert msg.data == {"hello": "world"}
