"""Tests for permissions/checker.py — permission tier enforcement (REQ-03)."""

from __future__ import annotations

import pytest

from guild.permissions.checker import HARDCODED_NEVER, PermissionChecker, PermissionTier

# ---------------------------------------------------------------------------
# REQ-03.1: Tier 0 "Nothing" — no tool use at all
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNothingTier:
    """Nothing tier blocks all tool invocations unconditionally."""

    def test_nothing_tier_blocks_all_tools(self) -> None:
        """Nothing tier returns False for any tool call."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        assert checker.check("file_read", "agent-1", {"path": "/tmp/x"}) is False

    def test_nothing_tier_blocks_regardless_of_tool_name(self) -> None:
        """Nothing tier blocks even well-known safe tools."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        assert checker.check("shell_exec", "agent-1", {"cmd": "ls"}) is False
        assert checker.check("file_write", "agent-2", {"path": "a.txt"}) is False
        assert checker.check("any_tool", "agent-3", {}) is False

    def test_nothing_tier_blocks_even_read_only_tools(self) -> None:
        """Nothing tier blocks read-only tools like file_read and search."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        assert checker.check("file_read", "agent-1", {"path": "/tmp/safe.txt"}) is False
        assert checker.check("search", "agent-1", {"query": "hello"}) is False
        assert checker.check("glob", "agent-1", {"pattern": "*.py"}) is False

    def test_nothing_tier_returns_false_for_any_args(self) -> None:
        """Nothing tier blocks regardless of args — empty, missing, or complex."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        # Empty args
        assert checker.check("file_read", "agent-1", {}) is False
        # Complex nested args
        assert checker.check("shell", "agent-1", {"command": "ls", "timeout": 5}) is False
        # None-like values
        assert checker.check("shell", "agent-1", {"command": ""}) is False


# ---------------------------------------------------------------------------
# REQ-03.2: Tier 1 "Ask" — agent requests, human approves per-tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAskTier:
    """Ask tier delegates decisions to a prompt function."""

    def test_ask_tier_calls_prompt_function(self) -> None:
        """Ask tier invokes prompt_fn with tool name, agent id, and args."""
        calls: list[tuple[str, str, dict]] = []

        def prompt_fn(tool: str, agent_id: str, args: dict) -> bool:
            calls.append((tool, agent_id, args))
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=prompt_fn)
        result = checker.check("file_read", "agent-1", {"path": "/tmp/x"})

        assert result is True
        assert len(calls) == 1
        assert calls[0] == ("file_read", "agent-1", {"path": "/tmp/x"})

    def test_ask_tier_remembers_session_approval(self) -> None:
        """Once approved, same tool name does not re-prompt in same session."""
        call_count = 0

        def prompt_fn(tool: str, agent_id: str, args: dict) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=prompt_fn)
        checker.check("file_read", "agent-1", {"path": "/a"})
        checker.check("file_read", "agent-1", {"path": "/b"})

        # Only prompted once — second call used cached approval
        assert call_count == 1

    def test_ask_tier_denial_blocks_call(self) -> None:
        """If prompt_fn returns False, the tool call is denied."""

        def deny_all(tool: str, agent_id: str, args: dict) -> bool:
            return False

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=deny_all)
        assert checker.check("file_read", "agent-1", {"path": "/tmp"}) is False


# ---------------------------------------------------------------------------
# REQ-03.3: Tier 2 "Scoped" — all tools within defined scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScopedTier:
    """Scoped tier allows tools in the allowlist within path boundaries."""

    def test_scoped_tier_allows_tools_in_allowlist(self) -> None:
        """Tool in allowlist is permitted."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read", "file_write"],
            allowed_paths=["/project"],
        )
        result = checker.check("file_read", "agent-1", {"path": "/project/src/main.py"})
        assert result is True

    def test_scoped_tier_blocks_tools_not_in_allowlist(self) -> None:
        """Tool not in allowlist is denied."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read"],
            allowed_paths=["/project"],
        )
        result = checker.check("shell_exec", "agent-1", {"cmd": "rm -rf /"})
        assert result is False

    def test_scoped_tier_checks_path_boundaries(self) -> None:
        """Tool in allowlist with path inside boundary is allowed."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_write"],
            allowed_paths=["/home/user/project"],
        )
        result = checker.check(
            "file_write",
            "agent-1",
            {"path": "/home/user/project/src/app.py", "content": "x"},
        )
        assert result is True

    def test_scoped_tier_blocks_path_outside_boundary(self) -> None:
        """Tool in allowlist but path outside boundary is denied."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_write"],
            allowed_paths=["/home/user/project"],
        )
        result = checker.check(
            "file_write",
            "agent-1",
            {"path": "/etc/passwd", "content": "hacked"},
        )
        assert result is False

    def test_scoped_allows_when_no_path_in_args(self) -> None:
        """Tool in allowlist with no path arg is allowed (no boundary check)."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["search"],
            allowed_paths=["/project"],
        )
        result = checker.check("search", "agent-1", {"query": "hello"})
        assert result is True


# ---------------------------------------------------------------------------
# REQ-03.4: Tier 3 "Autopilot" — everything allowed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutopilotTier:
    """Autopilot tier allows all tools unconditionally."""

    def test_autopilot_tier_allows_everything(self) -> None:
        """Autopilot returns True for any tool."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert checker.check("shell_exec", "agent-1", {"cmd": "rm -rf /"}) is True

    def test_autopilot_tier_allows_any_path(self) -> None:
        """Autopilot does not enforce path boundaries."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        assert (
            checker.check("file_write", "agent-1", {"path": "/etc/shadow", "content": "x"}) is True
        )

    def test_autopilot_allows_shell_with_any_command(self) -> None:
        """Autopilot allows shell execution with any non-destructive command."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        # Various commands that are not in the hardcoded-never list
        assert checker.check("shell", "agent-1", {"command": "curl http://example.com"}) is True
        assert checker.check("shell", "agent-1", {"command": "python3 -c 'exit(0)'"}) is True
        assert checker.check("shell", "agent-1", {"command": "cat /etc/hostname"}) is True


# ---------------------------------------------------------------------------
# REQ-03.5: Permission level switchable at runtime
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetTier:
    """Runtime tier switching and its side effects."""

    def test_set_tier_changes_behavior(self) -> None:
        """Switching from NOTHING to AUTOPILOT changes check results."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        assert checker.check("file_read", "agent-1", {}) is False

        checker.set_tier(PermissionTier.AUTOPILOT)
        assert checker.check("file_read", "agent-1", {}) is True

    def test_set_tier_clears_session_approvals(self) -> None:
        """Changing tier resets cached approvals from ASK tier."""
        call_count = 0

        def prompt_fn(tool: str, agent_id: str, args: dict) -> bool:
            nonlocal call_count
            call_count += 1
            return True

        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=prompt_fn)
        # Approve file_read
        checker.check("file_read", "agent-1", {"path": "/a"})
        assert call_count == 1

        # Switch tier and back — should clear approvals
        checker.set_tier(PermissionTier.SCOPED, allowed_tools=["file_read"])
        checker.set_tier(PermissionTier.ASK, prompt_fn=prompt_fn)

        # Should re-prompt since approvals were cleared
        checker.check("file_read", "agent-1", {"path": "/b"})
        assert call_count == 2

    def test_switch_from_nothing_to_autopilot_allows_calls(self) -> None:
        """Switching from NOTHING to AUTOPILOT immediately allows all calls."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        # Confirm blocked first
        assert checker.check("shell", "agent-1", {"command": "echo hi"}) is False
        assert checker.check("file_write", "agent-1", {"path": "/x", "content": "y"}) is False

        # Switch to autopilot
        checker.set_tier(PermissionTier.AUTOPILOT)

        # Now everything should be allowed
        assert checker.check("shell", "agent-1", {"command": "echo hi"}) is True
        assert checker.check("file_write", "agent-1", {"path": "/x", "content": "y"}) is True
        assert checker.check("file_read", "agent-1", {"path": "/etc/passwd"}) is True


# ---------------------------------------------------------------------------
# REQ-03.7: Hardcoded-never layer — destructive/irreversible actions blocked
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHardcodedNever:
    """Hardcoded-never layer blocks destructive actions regardless of tier."""

    @pytest.mark.parametrize(
        "command",
        [
            "git push --force origin main",
            "rm -rf /",
            "git reset --hard HEAD~3",
            "git push -f origin main",
            "rm -rf ~/.",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda bs=1M",
            "sudo rm -rf /var/log",
            "git rebase main",
            "git branch -D main",
        ],
        ids=[
            "git_push_force",
            "rm_rf_slash",
            "git_reset_hard",
            "git_push_short_force",
            "rm_rf_home",
            "mkfs",
            "dd_device",
            "sudo_rm",
            "git_rebase_main",
            "git_branch_delete_main",
        ],
    )
    def test_hardcoded_never_blocks_destructive_command(self, command: str) -> None:
        """Destructive commands are blocked even in AUTOPILOT mode."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        result = checker.check("shell", "agent-1", {"command": command})
        assert result is False

    @pytest.mark.parametrize(
        "command",
        [
            "git push origin main",
            "rm temp_file.txt",
        ],
        ids=["safe_git_push", "safe_rm"],
    )
    def test_hardcoded_never_allows_safe_command(self, command: str) -> None:
        """Non-destructive commands pass through even in AUTOPILOT mode."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        result = checker.check("shell", "agent-1", {"command": command})
        assert result is True

    def test_hardcoded_never_returns_reason_when_blocked(self) -> None:
        """check_hardcoded_never returns a descriptive reason when blocking."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never(
            "shell", {"command": "git push --force origin main"}
        )
        assert allowed is False
        assert "git push --force" in reason
        assert "REQ-03.7" in reason

    def test_hardcoded_never_override_flag(self) -> None:
        """Explicit allow_hardcoded_never flag bypasses the layer."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never(
            "shell", {"command": "git push --force origin main"}, allow_hardcoded_never=True
        )
        assert allowed is True
        assert reason == ""

    def test_hardcoded_never_does_not_affect_non_shell_tools(self) -> None:
        """Non-shell tools are not subject to shell-specific patterns."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        # file_write is not "shell", so patterns don't apply
        result = checker.check("file_write", "agent-1", {"path": "/tmp/x", "content": "x"})
        assert result is True

    def test_hardcoded_never_works_with_cmd_key(self) -> None:
        """Shell tool using 'cmd' arg key is also checked."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        result = checker.check("shell", "agent-1", {"cmd": "git push --force origin main"})
        assert result is False

    def test_hardcoded_never_list_not_empty(self) -> None:
        """HARDCODED_NEVER has entries defined."""
        assert len(HARDCODED_NEVER) > 0
        for rule in HARDCODED_NEVER:
            assert "tool" in rule
            assert "pattern" in rule
            assert "reason" in rule


# ---------------------------------------------------------------------------
# REQ-03.6: Audit log of permission decisions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPermissionDecisionAuditable:
    """Permission decisions expose enough info for audit logging."""

    def test_permission_decision_is_auditable(self) -> None:
        """check() returns a bool, and the checker exposes tier + tool name.

        The caller (agent loop) has access to tool_name, the boolean result,
        and the checker's tier — all needed to write an audit entry.
        """
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        tool_name = "file_read"
        agent_id = "agent-1"
        args = {"path": "/tmp/x"}

        result = checker.check(tool_name, agent_id, args)

        # The caller has: tool_name (str), result (bool), tier (enum)
        assert isinstance(result, bool)
        assert result is True
        # Tier is accessible for logging
        assert checker._tier == PermissionTier.AUTOPILOT
        # Tool name and agent_id are the caller's own variables — always available

    def test_permission_denial_is_auditable(self) -> None:
        """Denied permission decisions also expose all required audit info."""
        checker = PermissionChecker(tier=PermissionTier.NOTHING)
        tool_name = "shell"
        agent_id = "agent-2"
        args = {"command": "ls"}

        result = checker.check(tool_name, agent_id, args)

        assert isinstance(result, bool)
        assert result is False
        assert checker._tier == PermissionTier.NOTHING

    def test_hardcoded_never_provides_reason_for_audit(self) -> None:
        """check_hardcoded_never returns a descriptive reason for logging."""
        checker = PermissionChecker(tier=PermissionTier.AUTOPILOT)
        allowed, reason = checker.check_hardcoded_never("shell", {"command": "rm -rf /"})
        assert allowed is False
        assert len(reason) > 0
        # Reason is suitable for writing to audit log
        assert "rm -rf /" in reason


# ---------------------------------------------------------------------------
# REQ-03.8: Reversibility — safe operations allowed in all tiers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReversibilitySafeOperations:
    """Safe, reversible operations remain allowed in all tiers."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "cat README.md",
            "git status",
            "git log --oneline",
            "git diff HEAD",
            "git push origin feature-branch",
            "rm temp.txt",
            "rm -r build/",
            "git branch -d feature-x",
            "git rebase feature-branch",
        ],
    )
    @pytest.mark.parametrize(
        "tier_setup",
        [
            ("SCOPED", {"allowed_tools": ["shell"], "allowed_paths": ["/"]}),
            ("AUTOPILOT", {}),
        ],
        ids=["scoped_tier", "autopilot_tier"],
    )
    def test_safe_operations_allowed(self, command: str, tier_setup: tuple) -> None:
        """Non-destructive commands pass in SCOPED and AUTOPILOT tiers."""
        tier_name, kwargs = tier_setup
        tier = PermissionTier(tier_name.lower())
        checker = PermissionChecker(tier=tier, **kwargs)

        result = checker.check("shell", "agent-1", {"command": command})
        assert result is True, f"Safe command '{command}' was blocked in tier {tier.value}"


# ======================================================================
# Permissions checker edges (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestPermissionsCheckerEdges:
    """Cover permissions checker uncovered branches."""

    def test_set_tier_updates_allowed_paths(self) -> None:
        """set_tier with allowed_paths updates the paths (line 175)."""
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
        checker = PermissionChecker(tier=PermissionTier.ASK, prompt_fn=None)
        result = checker.check("file_read", "agent-1", {"path": "/tmp/x"})
        assert result is False

    def test_scoped_path_exact_match(self) -> None:
        """Scoped tier allows path that exactly matches allowed path (line 224)."""
        checker = PermissionChecker(
            tier=PermissionTier.SCOPED,
            allowed_tools=["file_read"],
            allowed_paths=["/exact/path"],
        )
        result = checker.check("file_read", "agent-1", {"path": "/exact/path"})
        assert result is True
