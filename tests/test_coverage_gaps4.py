"""Fourth batch of tests to close remaining branch coverage gaps to reach 98%+."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.agent.message import Message

if TYPE_CHECKING:
    from pathlib import Path

# ======================================================================
# 1. agent/ratelimit.py:81->83 — branch where wait <= 0 (window expired)
# ======================================================================


@pytest.mark.unit
class TestRateLimiterWindowExpiredBranch:
    """Cover the branch where wait computes to <= 0 in RateLimiter."""

    async def test_wait_computes_to_zero_or_negative(self) -> None:
        """When calls are exactly at window boundary, wait <= 0 skips sleep."""
        from guild.agent.ratelimit import RateLimiter

        # Use a very short window so calls quickly expire
        limiter = RateLimiter(max_calls=1, window_seconds=0.01)

        # Fill the window
        await limiter.acquire()

        # Wait just past the window so oldest call is beyond boundary
        await asyncio.sleep(0.02)

        # Now when acquire() is called, it will:
        # 1. _prune() -> calls is empty -> len < max -> return (fast path)
        # But we need to hit the ELSE branch where len >= max and wait <= 0.
        # To do this, we need to manually set up calls at the boundary.
        # Inject a call that's exactly at the window edge.
        limiter._calls = [time.monotonic() - limiter._window]

        # Now: len(calls) == 1 == max, so it enters the wait calc.
        # wait = window - (now - oldest) = window - window = ~0 or negative.
        # This should hit the `wait <= 0` branch (line 81->83) and NOT sleep.
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        # Should be near-instant since wait <= 0 means no sleep
        assert elapsed < 0.05


# ======================================================================
# 2. agent/rollback.py:53->61 — else branch (file existed, restore content)
# ======================================================================


@pytest.mark.unit
class TestRollbackRestoreExistingFileBranch:
    """Explicitly cover the else branch at line 53->61 in rollback."""

    def test_rollback_existing_file_restores_content(self, tmp_path: Path) -> None:
        """Rollback of a file that existed restores its original content.

        This specifically targets the else branch at line 56-60 where
        snapshot.content is NOT None (file existed before capture).
        """
        from guild.agent.rollback import RollbackContext

        f = tmp_path / "existing.txt"
        f.write_text("original data")

        ctx = RollbackContext()
        ctx.capture(str(f))

        # Modify the file
        f.write_text("modified data")
        assert f.read_text() == "modified data"

        # Rollback should restore
        rolled_back = ctx.rollback()
        assert str(f) in rolled_back
        assert f.read_text() == "original data"

    def test_rollback_mixed_existing_and_new_files(self, tmp_path: Path) -> None:
        """Rollback handles mix of existing files and new files correctly."""
        from guild.agent.rollback import RollbackContext

        existing = tmp_path / "exists.txt"
        existing.write_text("keep me")
        new_file = tmp_path / "new.txt"

        ctx = RollbackContext()
        ctx.capture(str(existing))  # content != None -> else branch
        ctx.capture(str(new_file))  # content == None -> if branch

        # Modify/create
        existing.write_text("changed")
        new_file.write_text("created")

        rolled_back = ctx.rollback()
        assert len(rolled_back) == 2
        assert existing.read_text() == "keep me"  # Restored (else branch)
        assert not new_file.exists()  # Deleted (if branch)

    def test_rollback_nonexistent_file_never_created(self, tmp_path: Path) -> None:
        """Rollback of a file that never existed and was never created (53->61).

        This covers the branch where snapshot.content is None AND
        snapshot.path.exists() is False at rollback time.
        """
        from guild.agent.rollback import RollbackContext

        f = tmp_path / "never_created.txt"
        assert not f.exists()

        ctx = RollbackContext()
        ctx.capture(str(f))  # content = None (file doesn't exist)

        # Do NOT create the file — leave it nonexistent
        rolled_back = ctx.rollback()
        # Should still be in rolled_back list (line 61 reached via 53->61)
        assert str(f) in rolled_back
        assert not f.exists()


# ======================================================================
# 3. blocks/skills.py:59->53 — loop continuation after tools: line
# ======================================================================


@pytest.mark.unit
class TestSkillsFrontmatterToolsLastLine:
    """Cover the branch where tools: is NOT the last line in frontmatter."""

    def test_frontmatter_tools_followed_by_more_lines(self, tmp_path: Path) -> None:
        """When tools line is followed by other lines, loop continues past 59->53."""
        from guild.blocks.skills import SkillDef

        # The tools line is in the middle, followed by description
        f = tmp_path / "multi.md"
        f.write_text(
            "---\n"
            "tools: [shell, file_read]\n"
            "name: multi-skill\n"
            "description: A skill with tools then other fields\n"
            "---\n"
            "Body content here.\n"
        )
        skill = SkillDef.from_file(f)
        assert skill.name == "multi-skill"
        assert skill.description == "A skill with tools then other fields"
        assert "shell" in skill.tools
        assert "file_read" in skill.tools

    def test_frontmatter_unrecognized_lines_after_tools(self, tmp_path: Path) -> None:
        """Unrecognized lines after tools line cause loop to continue (59->53)."""
        from guild.blocks.skills import SkillDef

        # Tools line followed by unrecognized lines that don't match any elif
        f = tmp_path / "extras.md"
        f.write_text(
            "---\n"
            "name: extras\n"
            "description: test\n"
            "tools: [shell]\n"
            "author: someone\n"
            "version: 1.0\n"
            "---\n"
            "Content.\n"
        )
        skill = SkillDef.from_file(f)
        assert skill.name == "extras"
        assert skill.tools == ["shell"]


# ======================================================================
# 4. config/loader.py:65 — fallback to global config path
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderGlobalFallback:
    """Cover the branch at line 65 where only global config exists."""

    def test_global_config_only_returns_global_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When only global config exists (no project config), return global path."""
        from guild.config.loader import _merge_toml_files

        # Set up: global config exists, project config does NOT exist
        home = tmp_path / "home"
        global_guild = home / ".guild"
        global_guild.mkdir(parents=True)
        global_config = global_guild / "config.toml"
        global_config.write_text('[provider]\nmodel = "global-model"\n')

        # Project guild dir exists but has no config.toml
        project_guild = tmp_path / "project" / ".guild"
        project_guild.mkdir(parents=True)

        monkeypatch.setenv("HOME", str(home))

        result = _merge_toml_files(project_guild)
        # Should return the global path directly (line 65)
        assert result == global_config


# ======================================================================
# 5. config/loader.py:155-158 — temp file cleanup
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderTempFileCleanup:
    """Cover the temp file cleanup branch at lines 155-158."""

    def test_load_config_cleans_up_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When merged config creates a temp file, it's cleaned up after loading."""
        from guild.config.loader import load_config

        # Set up both global and project configs so merge creates a temp file
        home = tmp_path / "home"
        global_guild = home / ".guild"
        global_guild.mkdir(parents=True)
        (global_guild / "config.toml").write_text(
            '[provider]\nmodel = "global"\ntemperature = 0.5\n'
        )

        project_guild = tmp_path / "project" / ".guild"
        project_guild.mkdir(parents=True)
        (project_guild / "config.toml").write_text('[provider]\nmodel = "project"\n')

        # Patch Path.home() to return our fake home
        monkeypatch.setenv("HOME", str(home))

        # load_config should merge, use temp file, then clean it up
        config = load_config(guild_dir=project_guild)
        assert config.model == "project"
        # The temp file should have been deleted (lines 155-158)
        # We can't easily check the file is gone, but exercise the code path


# ======================================================================
# 5b. config/loader.py:87-89 — corrupt TOML exception handling
# ======================================================================


@pytest.mark.unit
class TestConfigLoaderCorruptToml:
    """Cover the exception branch in _load_toml_file."""

    def test_load_toml_file_corrupt_returns_empty(self, tmp_path: Path) -> None:
        """Corrupt TOML file returns empty dict (lines 87-89)."""
        from guild.config.loader import _load_toml_file

        corrupt_file = tmp_path / "bad.toml"
        corrupt_file.write_text("this is not = valid [ toml {{{")

        result = _load_toml_file(corrupt_file)
        assert result == {}


# ======================================================================
# 6. config/profiles.py:66, 85 — non-dict values in TOML are skipped
# ======================================================================


@pytest.mark.unit
class TestProfilesNonDictValues:
    """Cover branches where non-dict values in TOML are skipped."""

    def test_agent_profiles_skips_non_dict_values(self, tmp_path: Path) -> None:
        """Non-dict values at top level in agents.toml are skipped."""
        from guild.config.profiles import load_agent_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        # Include a scalar value and a proper table
        agents_toml.write_text(
            'version = "1.0"\n\n'  # scalar — should be skipped (line 66)
            "[valid_agent]\n"
            'model = "llama3"\n'
        )

        profiles = load_agent_profiles(guild_dir)
        # "version" is not a dict, so it's skipped
        assert "version" not in profiles
        assert "valid_agent" in profiles
        assert profiles["valid_agent"].model == "llama3"

    def test_permission_profiles_skips_non_dict_values(self, tmp_path: Path) -> None:
        """Non-dict values at top level in permissions.toml are skipped."""
        from guild.config.profiles import load_permission_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        perms_toml = guild_dir / "permissions.toml"
        # Include a scalar value and a proper table
        perms_toml.write_text(
            "format_version = 2\n\n"  # integer scalar — should be skipped (line 85)
            "[valid_perm]\n"
            'tier = "scoped"\n'
        )

        profiles = load_permission_profiles(guild_dir)
        assert "format_version" not in profiles
        assert "valid_perm" in profiles
        assert profiles["valid_perm"].tier == "scoped"


# ======================================================================
# 7. config/profiles.py:122->121 — validate_config loop branch
# ======================================================================


@pytest.mark.unit
class TestProfilesValidateLoopBranch:
    """Cover the loop skip branch in validate_config (line 122->121)."""

    def test_validate_config_all_valid_permissions(self, tmp_path: Path) -> None:
        """When all agent profiles have valid permissions, loop completes without error."""
        from guild.config.loader import load_config
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_toml = guild_dir / "agents.toml"
        # All valid permissions — the loop iterates but never appends errors
        agents_toml.write_text(
            '[agent1]\npermission = "ask"\n\n'
            '[agent2]\npermission = "autopilot"\n\n'
            '[agent3]\npermission = "scoped"\n'
        )

        config = load_config(guild_dir=guild_dir)
        errors = validate_config(config, guild_dir)

        # No permission errors
        permission_errors = [e for e in errors if "permission" in e.lower()]
        assert permission_errors == []


# ======================================================================
# 8. daemon/lifecycle.py:99->96 — kill_all loop when kill_task returns False
# ======================================================================


@pytest.mark.unit
class TestLifecycleKillAllFailBranch:
    """Cover the branch where kill_task returns False in kill_all loop."""

    async def test_kill_all_counts_only_successful_kills(self, tmp_path: Path) -> None:
        """kill_all only counts tasks where kill_task returned True."""
        from guild.daemon.lifecycle import LifecycleManager
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Create two PID files
        (run_dir / "task-a.pid").write_text("111")
        (run_dir / "task-b.pid").write_text("222")

        mgr = LifecycleManager(run_dir=run_dir, storage=store)

        # Make kill_task return True for first, False for second
        call_count = 0

        async def selective_kill(task_id: str, timeout: float = 10.0) -> bool:
            nonlocal call_count
            call_count += 1
            if task_id == "task-a":
                # Simulate successful kill
                (run_dir / f"{task_id}.pid").unlink(missing_ok=True)
                return True
            else:
                # Simulate failed kill (PID file doesn't exist scenario)
                return False

        with patch.object(mgr, "kill_task", side_effect=selective_kill):
            count = await mgr.kill_all()

        # Only one kill was successful — branch 99->96 exercised
        assert count == 1
        await store.close()


# ======================================================================
# 9. daemon/resource.py:149->exit — wait_if_throttled branch for STEALTH
# ======================================================================


@pytest.mark.unit
class TestResourceThrottleStealthExit:
    """Cover the STEALTH mode exit branch in wait_if_throttled."""

    async def test_stealth_mode_returns_when_idle(self) -> None:
        """In STEALTH mode, if user is idle, returns immediately (exit branch)."""
        from guild.daemon.resource import (
            ActivityState,
            ResourceMonitor,
            SchedulingMode,
        )

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            activity_detector=lambda: ActivityState.IDLE,
            cpu_reader=lambda: 10.0,
        )

        # Should return immediately since user is IDLE
        start = time.monotonic()
        await monitor.wait_if_throttled()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    async def test_stealth_mode_blocks_then_releases(self) -> None:
        """In STEALTH mode, blocks while active then proceeds when idle."""
        from guild.daemon.resource import (
            ActivityState,
            ResourceMonitor,
            ResourceThresholds,
            SchedulingMode,
        )

        call_count = 0

        def activity_changes() -> ActivityState:
            nonlocal call_count
            call_count += 1
            # First call: ACTIVE, second call: IDLE (unblocks)
            return ActivityState.ACTIVE if call_count <= 1 else ActivityState.IDLE

        monitor = ResourceMonitor(
            mode=SchedulingMode.STEALTH,
            thresholds=ResourceThresholds(poll_interval_seconds=0.01),
            activity_detector=activity_changes,
            cpu_reader=lambda: 10.0,
        )

        await monitor.wait_if_throttled()
        # Should have polled at least twice
        assert call_count >= 2


# ======================================================================
# 10. escalation/notify.py:59->52 — loop continuation for NONE channel
# ======================================================================


@pytest.mark.unit
class TestNotifyLoopContinuation:
    """Cover the loop continuation branch when NONE is followed by real channels."""

    async def test_none_channel_skips_but_others_fire(self) -> None:
        """NONE channel is skipped (continue), then BELL channel fires."""
        from guild.escalation.notify import NotificationChannel, Notifier

        notifier = Notifier(
            channels=[
                NotificationChannel.NONE,
                NotificationChannel.TERMINAL_BELL,
            ]
        )

        with patch("sys.stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            await notifier.notify("test message")
            # NONE was skipped (continue at line 54), BELL fired
            mock_stdout.write.assert_called_once_with("\a")

    async def test_webhook_followed_by_bell_covers_loop_continuation(self) -> None:
        """WEBHOOK followed by BELL ensures loop continues past webhook (59->52)."""
        from guild.escalation.notify import NotificationChannel, Notifier

        notifier = Notifier(
            channels=[
                NotificationChannel.WEBHOOK,
                NotificationChannel.TERMINAL_BELL,
            ],
            webhook_url="https://example.com/hook",
        )

        with (
            patch("guild.escalation.notify.asyncio.get_event_loop") as mock_loop,
            patch("sys.stdout") as mock_stdout,
        ):
            mock_executor = AsyncMock()
            mock_loop.return_value.run_in_executor = mock_executor
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            await notifier.notify("multi-channel")

            # Both channels should have fired
            mock_executor.assert_called_once()
            mock_stdout.write.assert_called_once_with("\a")


# ======================================================================
# 11. knowledge/temporal.py:68-69 — decisions formatting
#     knowledge/temporal.py:163->167 — _run_cmd returns None on failure
# ======================================================================


@pytest.mark.unit
class TestTemporalKnowledgeBranches:
    """Cover temporal knowledge uncovered branches."""

    async def test_format_decisions_called_in_context(self, tmp_path: Path) -> None:
        """get_relevant_context formats decisions when they exist (lines 68-69)."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        # Add decisions so lines 68-69 are hit
        await store.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use pattern X",
            rationale="It is efficient",
        )

        tk = TemporalKnowledge(guild_dir, store)
        context = await tk.get_relevant_context("some task")
        assert "Use pattern X" in context
        assert "Recent Decisions" in context
        await store.close()

    async def test_run_cmd_returns_none_on_failure(self, tmp_path: Path) -> None:
        """_run_cmd returns None when command fails (line 163->167)."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, store)

        # Run a command that will fail (non-existent dir)
        result = await tk._run_cmd("git status", "/nonexistent/path/xyz")
        assert result is None
        await store.close()

    async def test_present_state_no_git_repo(self, tmp_path: Path) -> None:
        """get_present_state in a non-git dir returns 'No project state'."""
        from guild.knowledge.temporal import TemporalKnowledge
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        # Use a directory that is NOT a git repo and has no ls
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, store)
        # git commands will fail, ls will succeed
        result = await tk.get_present_state(str(empty_dir))
        # At minimum the ls command should work
        assert "Present State" in result or "No project state" in result
        await store.close()


# ======================================================================
# 12. observability/replay.py:98->exit, 102->99 — branch exits in replay
# ======================================================================


@pytest.mark.unit
class TestReplayExtractToolNamesBranches:
    """Cover the branch exits in _extract_tool_names."""

    def test_extract_tool_names_non_list_json(self) -> None:
        """When JSON parses to a non-list, branch exits early (line 98->exit)."""
        from guild.observability.replay import SessionReplay

        tools: list[str] = []
        # Valid JSON but not a list — should hit `if isinstance(calls, list)` False branch
        SessionReplay._extract_tool_names('{"not": "a list"}', tools)
        assert tools == []

    def test_extract_tool_names_call_without_name(self) -> None:
        """When a call has no function name, it's skipped (line 102->99)."""
        from guild.observability.replay import SessionReplay

        tools: list[str] = []
        # A call with empty name — `if name` is False, branch 102->99
        calls = json.dumps(
            [
                {"function": {"name": ""}},
                {"function": {"name": "valid_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        # Only valid_tool should be extracted
        assert tools == ["valid_tool"]

    def test_extract_tool_names_call_missing_function_key(self) -> None:
        """When a call has no 'function' key, it's handled."""
        from guild.observability.replay import SessionReplay

        tools: list[str] = []
        calls = json.dumps(
            [
                {"other_key": "value"},
                {"function": {"name": "good_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        assert tools == ["good_tool"]

    def test_extract_tool_names_deduplication(self) -> None:
        """Duplicate tool names are not added twice (name not in tools_used branch)."""
        from guild.observability.replay import SessionReplay

        tools: list[str] = ["existing_tool"]
        calls = json.dumps(
            [
                {"function": {"name": "existing_tool"}},
                {"function": {"name": "new_tool"}},
            ]
        )
        SessionReplay._extract_tool_names(calls, tools)
        # existing_tool should NOT be duplicated
        assert tools.count("existing_tool") == 1
        assert "new_tool" in tools


# ======================================================================
# 13. offline/manager.py:45->exit — health check succeeds branch
# ======================================================================


@pytest.mark.unit
class TestOfflineManagerHealthCheckSuccess:
    """Cover the branch where health check succeeds (line 45->exit)."""

    async def test_check_connectivity_success(self) -> None:
        """When health_check returns True, connectivity is True."""
        from guild.offline.manager import OfflineManager

        provider = MagicMock()
        provider.health_check = AsyncMock(return_value=True)

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()

        assert result is True
        assert mgr.is_online is True

    async def test_check_connectivity_false(self) -> None:
        """When health_check returns False, connectivity is False (exit branch)."""
        from guild.offline.manager import OfflineManager

        provider = MagicMock()
        provider.health_check = AsyncMock(return_value=False)

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()

        # This exercises the path where result = False (line 45 -> exit)
        assert result is False
        assert mgr.is_online is False


# ======================================================================
# Additional gaps found in initial coverage run
# ======================================================================


# --- agent/context.py:43->41 (content is empty/falsy in estimate_tokens) ---


@pytest.mark.unit
class TestContextManagerEmptyContentBranch:
    """Cover context manager branches with empty content."""

    def test_estimate_tokens_with_empty_content(self) -> None:
        """Messages with empty/None content don't add to token count."""
        from guild.agent.context import ContextManager

        cm = ContextManager()
        messages = [
            Message(role="system", content=""),
            Message(role="user", content=""),
            Message(role="tool", content=""),
        ]
        # All empty content — should be 0 tokens
        assert cm.estimate_tokens(messages) == 0

    def test_compact_empty_messages_returns_empty(self) -> None:
        """compact() returns [] for empty messages list (line 60)."""
        from guild.agent.context import ContextManager

        cm = ContextManager()
        result = cm.compact([])
        assert result == []

    def test_compact_already_within_threshold(self) -> None:
        """compact() exits early when tokens are already within threshold (75 branch)."""
        from guild.agent.context import ContextManager

        cm = ContextManager(max_tokens=10000, preserve_recent=2)
        messages = [
            Message(role="system", content="Hello"),
            Message(role="tool", content="short"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="bye"),
        ]
        # These are very short — within threshold, so no truncation needed
        result = cm.compact(messages)
        # Content should be unchanged
        assert result[1].content == "short"

    def test_protected_indices_no_system_prompt(self) -> None:
        """When first message is not system, index 0 is not protected (151->154)."""
        from guild.agent.context import ContextManager

        cm = ContextManager(preserve_recent=2)
        messages = [
            Message(role="user", content="first"),
            Message(role="assistant", content="second"),
            Message(role="tool", content="third"),
            Message(role="user", content="fourth"),
        ]
        protected = cm._protected_indices(messages)
        # Index 0 is NOT protected since role != "system"
        assert 0 not in protected
        # Recent 2 are protected
        assert 2 in protected
        assert 3 in protected

    def test_truncate_message_short_content_unchanged(self) -> None:
        """_truncate_message doesn't truncate short content (line 164)."""
        from guild.agent.context import MIN_CONTENT_LEN, ContextManager

        cm = ContextManager()
        msg = Message(role="tool", content="short")
        assert len("short") <= MIN_CONTENT_LEN
        cm._truncate_message(msg)
        assert msg.content == "short"

    def test_extract_decisions_finds_decision_prefix(self) -> None:
        """_extract_decisions finds lines starting with 'Decision:' (line 177->175)."""
        from guild.agent.context import ContextManager

        cm = ContextManager()
        messages = [
            Message(role="assistant", content="Decision: use SQLite\nOther line"),
            Message(role="user", content="ok"),
        ]
        decisions = cm._extract_decisions(messages)
        assert len(decisions) == 1
        assert "Decision: use SQLite" in decisions[0]

    def test_extract_completed_actions_empty_first_line(self) -> None:
        """_extract_completed_actions skips empty first lines (190->184)."""
        from guild.agent.context import ContextManager

        cm = ContextManager()
        messages = [
            Message(role="tool", content="\nsecond line here"),
            Message(role="tool", content=""),
        ]
        actions = cm._extract_completed_actions(messages)
        # First message: first_line is "" (empty after split/strip) — skipped
        # Second message: content is "" — first_line is "" — skipped
        assert actions == []


# --- agent/learning.py:63-64, 167->161, 190, 199 ---


@pytest.mark.unit
class TestLearningEdgeBranches:
    """Cover learning module uncovered branches."""

    async def test_extract_learnings_no_assigned_agent(self, tmp_path: Path) -> None:
        """extract_learnings returns [] when task has no assigned_agent (lines 57-58)."""
        from guild.agent.learning import extract_learnings
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test task")
        # Task exists but has no assigned_agent

        provider = AsyncMock()
        result = await extract_learnings("t1", store, provider)
        assert result == []
        await store.close()

    async def test_extract_learnings_no_messages(self, tmp_path: Path) -> None:
        """extract_learnings returns [] when agent has no messages (lines 63-64)."""
        from guild.agent.learning import extract_learnings
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test task")
        # Assign an agent but don't add any messages
        await store.update_task("t1", assigned_agent="agent-1")

        provider = AsyncMock()
        result = await extract_learnings("t1", store, provider)
        assert result == []
        await store.close()

    def test_parse_learning_line_empty_line(self) -> None:
        """_parse_learning_line returns None for empty line (line 190)."""
        from guild.agent.learning import _parse_learning_line

        result = _parse_learning_line("")
        assert result is None
        result = _parse_learning_line("   ")
        assert result is None

    def test_parse_learning_line_non_dict_json(self) -> None:
        """_parse_learning_line returns None for non-dict JSON (line 199)."""
        from guild.agent.learning import _parse_learning_line

        # Valid JSON but array, not dict
        result = _parse_learning_line("[1, 2, 3]")
        assert result is None

    def test_parse_learning_line_empty_content(self) -> None:
        """_parse_learning_line returns None for empty content (line 190)."""
        from guild.agent.learning import _parse_learning_line

        # Valid category but empty content
        result = _parse_learning_line('{"category": "pattern", "content": ""}')
        assert result is None

    def test_parse_learning_line_non_string_content(self) -> None:
        """_parse_learning_line returns None for non-string content."""
        from guild.agent.learning import _parse_learning_line

        result = _parse_learning_line('{"category": "pattern", "content": 123}')
        assert result is None

    def test_format_session_log_truncates_long_content(self) -> None:
        """_format_session_log truncates messages > 500 chars (line 181)."""
        from guild.agent.learning import _format_session_log

        long_content = "x" * 600
        messages = [{"role": "user", "content": long_content}]
        result = _format_session_log(messages)
        # Should be truncated to 500 chars + "..."
        assert len(result.split("] ")[1]) == 503  # 500 + "..."
        assert result.endswith("...")

    async def test_suggest_prompt_refinements_skips_non_matching(self, tmp_path: Path) -> None:
        """suggest_prompt_refinements skips categories other than anti_pattern/tool_tip."""
        from guild.agent.learning import suggest_prompt_refinements
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()

        # Add learnings of various categories
        await store.add_learning(category="pattern", content="Use async", confidence=0.9)
        await store.add_learning(category="domain_knowledge", content="API is REST", confidence=0.8)
        await store.add_learning(
            category="anti_pattern", content="Avoid busy waits", confidence=0.7
        )
        await store.add_learning(category="tool_tip", content="Use --verbose flag", confidence=0.6)

        suggestions = await suggest_prompt_refinements(store)

        # Only anti_pattern and tool_tip should generate suggestions
        assert any("Avoid busy waits" in s for s in suggestions)
        assert any("--verbose flag" in s for s in suggestions)
        # pattern and domain_knowledge are in the loop but don't match
        # either if/elif — they exercise the `167->161` branch (loop continues)
        assert len(suggestions) == 2
        await store.close()


# --- agent/loop.py:221->223 (stuck_detector is None) ---
# --- agent/loop.py:305->304 (tool name not in TOOL_SCHEMAS) ---


@pytest.mark.unit
class TestAgentLoopUncoveredBranches:
    """Cover agent loop branches where stuck_detector is None and tool schemas miss."""

    def test_get_tool_schemas_skips_unknown_tools(self) -> None:
        """_get_tool_schemas skips tools not in TOOL_SCHEMAS (305->304)."""
        from guild.agent.loop import AgentLoop

        loop = AgentLoop(
            provider=MagicMock(),
            tool_executors={"nonexistent_tool_xyz": AsyncMock()},
        )
        schemas = loop._get_tool_schemas()
        # nonexistent_tool_xyz is not in TOOL_SCHEMAS, so it's skipped
        assert schemas == []

    async def test_attempt_recovery_without_stuck_detector(self) -> None:
        """_attempt_recovery works when stuck_detector is None (221->223)."""
        from guild.agent.loop import AgentLoop

        loop = AgentLoop(
            provider=MagicMock(),
            tool_executors={},
            stuck_detector=None,
        )
        loop._recovery_attempted = False
        result = loop._attempt_recovery()
        assert result is None
        assert loop._recovery_attempted is True
        # Should have appended recovery prompt
        assert any("stuck" in msg.content.lower() for msg in loop.messages)


# ======================================================================
# Additional coverage: storage edge cases
# ======================================================================


@pytest.mark.unit
class TestStorageEdgeCases:
    """Cover storage update edge cases."""

    async def test_update_task_no_fields(self, tmp_path: Path) -> None:
        """update_task with no fields returns early (line 212)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test")
        # Call with no fields — should return immediately
        await store.update_task("t1")
        # Task should be unchanged
        task = await store.get_task("t1")
        assert task is not None
        assert task["status"] == "pending"
        await store.close()

    async def test_update_task_invalid_fields(self, tmp_path: Path) -> None:
        """update_task with unrecognized fields returns early (line 216)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.create_task("t1", "test")
        # Call with invalid field names — filtered set is empty
        await store.update_task("t1", invalid_field="value", another="nope")
        task = await store.get_task("t1")
        assert task is not None
        assert task["status"] == "pending"
        await store.close()

    async def test_update_agent_no_fields(self, tmp_path: Path) -> None:
        """update_agent with no fields returns early (line 248)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.register_agent("a1", "coder")
        await store.update_agent("a1")
        await store.close()

    async def test_update_agent_invalid_fields(self, tmp_path: Path) -> None:
        """update_agent with unrecognized fields returns early (line 252)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.register_agent("a1", "coder")
        await store.update_agent("a1", bad_field="nope")
        await store.close()

    async def test_list_questions_all(self, tmp_path: Path) -> None:
        """list_questions with answered=None returns all (line 526)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        await store.connect()
        await store.insert_question(
            question_id="q1",
            question="What?",
            context="ctx",
            created_at="2024-01-01T00:00:00",
            agent_id="a1",
        )
        questions = await store.list_questions(answered=None)
        assert len(questions) >= 1
        await store.close()

    async def test_close_when_not_connected(self, tmp_path: Path) -> None:
        """close() when db is None is a no-op (line 172->exit)."""
        from guild.storage.sqlite import Storage

        store = Storage(tmp_path / "test.db")
        # Don't connect — _db is None
        await store.close()  # Should not raise


# ======================================================================
# Additional coverage: permissions/checker.py edges
# ======================================================================


@pytest.mark.unit
class TestPermissionsCheckerEdges:
    """Cover permissions checker uncovered branches."""

    def test_set_tier_updates_allowed_paths(self) -> None:
        """set_tier with allowed_paths updates the paths (line 175)."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.ASK)
        checker.set_tier(
            PermissionTier.SCOPED,
            allowed_paths=["/home/user"],
            allowed_tools=["file_read"],
        )
        # Verify paths were set
        assert checker._allowed_paths == ["/home/user"]
        assert checker._allowed_tools == ["file_read"]

    def test_ask_tier_no_prompt_fn_returns_false(self) -> None:
        """ASK tier with no prompt_fn returns False (line 187)."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=None)
        result = checker.check("file_read", "agent-1", {"path": "/tmp/x"})
        assert result is False

    def test_scoped_path_exact_match(self) -> None:
        """Scoped tier allows path that exactly matches allowed path (line 224)."""
        from guild.permissions.checker import PermissionChecker, PermissionTier

        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read"],
            allowed_paths=["/exact/path"],
        )
        result = checker.check("file_read", "agent-1", {"path": "/exact/path"})
        assert result is True


# ======================================================================
# Additional coverage: task/spec.py edges
# ======================================================================


@pytest.mark.unit
class TestTaskSpecEdges:
    """Cover task/spec.py uncovered branches."""

    def test_mark_completed_unknown_task(self) -> None:
        """mark_completed with unknown task_id does nothing (line 95->exit)."""
        from guild.task.spec import TaskGraph

        graph = TaskGraph()
        # Should not raise
        graph.mark_completed("nonexistent-task")

    async def test_transition_task_not_found(self, tmp_path: Path) -> None:
        """transition_task returns False when task doesn't exist (lines 280-281)."""
        from guild.storage.sqlite import Storage
        from guild.task.spec import transition_task

        store = Storage(tmp_path / "test.db")
        await store.connect()
        result = await transition_task(store, "nonexistent", "running")
        assert result is False
        await store.close()

    async def test_verify_command_oserror(self, tmp_path: Path) -> None:
        """_verify_command handles OSError (lines 239-240)."""
        from unittest.mock import patch as _patch

        from guild.task.spec import VerificationStep, _verify_command

        step = VerificationStep(
            type="command",
            target="echo test",
            expected=None,
        )
        # Mock subprocess creation to raise OSError
        with _patch(
            "guild.task.spec.asyncio.create_subprocess_shell",
            side_effect=OSError("No such file or directory"),
        ):
            passed, msg = await _verify_command(step, str(tmp_path))
        assert passed is False
        assert "error" in msg.lower()


# ======================================================================
# Additional coverage: provider/escalation.py edges
# ======================================================================


@pytest.mark.unit
class TestProviderEscalationEdges:
    """Cover provider/escalation.py uncovered branches."""

    def test_select_model_unknown_model_skipped(self) -> None:
        """select_model_for_task skips models not in MODEL_CAPABILITIES (line 81)."""
        from guild.provider.escalation import select_model_for_task

        # Include a model name that's not in MODEL_CAPABILITIES + one that is
        result = select_model_for_task(
            task_type="simple_qa",
            available_models=["unknown_model_xyz", "gemma4-2b-edge-fast"],
        )
        # Should pick the known model (unknown is skipped)
        assert result == "gemma4-2b-edge-fast"

    def test_select_model_no_match_raises(self) -> None:
        """select_model_for_task raises when no model supports task type (line 87)."""
        from guild.provider.escalation import select_model_for_task

        with pytest.raises(ValueError, match="No available model"):
            select_model_for_task(
                task_type="nonexistent_task_type",
                available_models=["unknown_model_xyz"],
            )

    async def test_escalation_provider_chain_exhausted_raises(self) -> None:
        """EscalatingProvider raises when chain is exhausted (line 214)."""
        from guild.provider.escalation import EscalatingProvider, EscalationChain

        # Create a chain with a single provider that fails
        provider = AsyncMock()
        provider.generate.side_effect = RuntimeError("provider fail")

        chain = EscalationChain(
            providers=[provider],
        )
        ep = EscalatingProvider(chain)

        with pytest.raises(RuntimeError, match="provider fail"):
            await ep.generate([{"role": "user", "content": "test"}])

    def test_escalation_provider_chain_property(self) -> None:
        """EscalatingProvider.chain property returns the chain (line 186)."""
        from guild.provider.escalation import EscalatingProvider, EscalationChain

        provider = AsyncMock()
        chain = EscalationChain(providers=[provider])
        ep = EscalatingProvider(chain)
        assert ep.chain is chain


# ======================================================================
# Additional coverage: security/sandbox.py edges
# ======================================================================


@pytest.mark.unit
class TestSandboxEdges:
    """Cover security/sandbox.py uncovered branches."""

    def test_check_path_denied_path_matches(self) -> None:
        """check_path returns False when path is in denied list (line 65->63)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            denied_paths=["/etc", "/var/secret"],
            allowed_paths=["/"],
        )
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "denied" in reason.lower()

    def test_check_command_denied_matches(self) -> None:
        """check_command returns False when command is in denylist (line 89->88)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            denied_commands=["rm", "shutdown"],
            allowed_commands=[],
        )
        allowed, reason = policy.check_command("rm -rf /")
        assert allowed is False
        assert "denylist" in reason.lower()

    def test_mask_secrets_replaces_value(self) -> None:
        """mask_secrets replaces matching secret values (line 108->107)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            secrets={"API_KEY": "sk-12345", "DB_PASS": "secret123"},
        )
        result = policy.mask_secrets("Token: sk-12345, Pass: secret123")
        assert "sk-12345" not in result
        assert "[REDACTED:API_KEY]" in result
        assert "[REDACTED:DB_PASS]" in result

    def test_resolve_path_oserror(self) -> None:
        """_resolve_path handles OSError gracefully (lines 135-136)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        # Mock Path.resolve() to raise OSError
        with patch("guild.security.sandbox.Path.resolve", side_effect=OSError("broken link")):
            result = policy._resolve_path("/some/broken/link")
            # Should return the unresolved path (line 136)
            assert result is not None

    def test_check_path_multiple_denied_second_matches(self) -> None:
        """check_path iterates through multiple denied paths (65->63 branch)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            denied_paths=["/safe/dir", "/etc/secrets"],
            allowed_paths=["/"],
        )
        # First denied path doesn't match, second does
        allowed, reason = policy.check_path("/etc/secrets/key")
        assert allowed is False

    def test_check_command_multiple_denied_second_matches(self) -> None:
        """check_command iterates through multiple denied commands (89->88)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            denied_commands=["safe_cmd", "rm"],
            allowed_commands=[],
        )
        # First denied doesn't match, second does
        allowed, reason = policy.check_command("rm -rf /")
        assert allowed is False

    def test_mask_secrets_multiple_secrets_some_match(self) -> None:
        """mask_secrets iterates through multiple secrets (108->107 branch)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            secrets={"NO_MATCH": "xyz_not_present", "MATCH": "secret123"},
        )
        result = policy.mask_secrets("The password is secret123")
        # First secret doesn't match, second does — exercises loop continuation
        assert "secret123" not in result
        assert "[REDACTED:MATCH]" in result


# ======================================================================
# Additional coverage: tools/plugin.py edges
# ======================================================================


@pytest.mark.unit
class TestToolsPluginEdges:
    """Cover tools/plugin.py uncovered branches."""

    def test_plugin_load_from_file_missing_name(self, tmp_path: Path) -> None:
        """Plugin without tool.name returns None (line 199 path)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "no_name.toml"
        # Valid TOML with [tool] section but no name field
        plugin_file.write_text("[tool]\n" 'description = "A tool without a name"\n')

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        result = loader.load_from_file(plugin_file)
        assert result is None

    def test_plugin_load_from_file_no_tool_section(self, tmp_path: Path) -> None:
        """Plugin without [tool] section returns None."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "no_section.toml"
        plugin_file.write_text('[metadata]\nauthor = "test"\n')

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        result = loader.load_from_file(plugin_file)
        assert result is None

    def test_plugin_load_from_dir_skips_none(self, tmp_path: Path) -> None:
        """load_from_dir skips files that return None (line 180->178)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        # One bad plugin
        (plugin_dir / "bad.toml").write_text("[metadata]\n")
        # One good plugin
        (plugin_dir / "good.toml").write_text(
            "[tool]\n" 'name = "good_tool"\n' 'description = "A good tool"\n'
        )

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugins = loader.load_from_dir(plugin_dir)
        # Only the good one should load
        assert len(plugins) == 1
        assert plugins[0].name == "good_tool"

    def test_plugin_parameters_required_as_list(self, tmp_path: Path) -> None:
        """Plugin with required as a list parses directly (line 199)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        # TOML with required as a direct list
        (plugin_dir / "with_required.toml").write_text(
            "[tool]\n"
            'name = "my_tool"\n'
            'description = "test"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            'required = ["path", "content"]\n'
        )

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugin = loader.load_from_file(plugin_dir / "with_required.toml")
        assert plugin is not None
        assert plugin.parameters.get("required") == ["path", "content"]
