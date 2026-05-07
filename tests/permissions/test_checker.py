"""Tests for permissions/checker.py — permission tier enforcement (REQ-03)."""

from __future__ import annotations

import pytest

from guild.permissions.checker import PermissionChecker, PermissionTier

# ---------------------------------------------------------------------------
# REQ-03.1: Tier 0 "Nothing" — no tool use at all
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-03.1")
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


# ---------------------------------------------------------------------------
# REQ-03.2: Tier 1 "Ask" — agent requests, human approves per-tool
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-03.2")
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
@pytest.mark.req("REQ-03.3")
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
@pytest.mark.req("REQ-03.4")
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


# ---------------------------------------------------------------------------
# REQ-03.5: Permission level switchable at runtime
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-03.5")
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
