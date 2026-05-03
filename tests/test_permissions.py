"""Tests for core/permissions.py — all 4 tiers, path scoping, session approvals."""

import pytest

pytestmark = pytest.mark.unit
from pathlib import Path

from guild.core.models import PermissionTier
from guild.core.permissions import PermissionChecker


class TestNothingTier:
    def test_denies_everything(self):
        pc = PermissionChecker(PermissionTier.NOTHING)
        assert pc.check("file_read", "a1", {"path": "/tmp/x"}) is False
        assert pc.check("shell", "a1", {"command": "ls"}) is False


class TestAutopilotTier:
    def test_allows_everything(self):
        pc = PermissionChecker(PermissionTier.AUTOPILOT)
        assert pc.check("file_read", "a1", {"path": "/etc/passwd"}) is True
        assert pc.check("shell", "a1", {"command": "rm -rf /"}) is True


class TestAskTier:
    def test_prompts_user(self):
        responses = iter(["y"])
        pc = PermissionChecker(
            PermissionTier.ASK,
            prompt_fn=lambda *_: next(responses) == "y",
        )
        assert pc.check("file_read", "a1", {"path": "/tmp/x"}) is True

    def test_deny_on_no(self):
        pc = PermissionChecker(
            PermissionTier.ASK,
            prompt_fn=lambda *_: False,
        )
        assert pc.check("file_read", "a1", {"path": "/tmp/x"}) is False

    def test_session_approval_remembered(self):
        """After 'always' approval, same tool should not prompt again."""
        call_count = 0
        def mock_prompt(tool, agent, args):
            nonlocal call_count
            call_count += 1
            return True
        pc = PermissionChecker(PermissionTier.ASK, prompt_fn=mock_prompt)
        # Simulate 'always' by directly adding to session approvals
        pc._session_approvals.add("file_read")
        assert pc.check("file_read", "a1", {"path": "/tmp/x"}) is True
        assert call_count == 0  # should not have prompted


class TestScopedTier:
    def test_allows_within_scope(self, tmp_path):
        pc = PermissionChecker(
            PermissionTier.SCOPED,
            allowed_paths=[str(tmp_path)],
        )
        assert pc.check("file_read", "a1", {"path": str(tmp_path / "foo.py")}) is True

    def test_denies_outside_scope(self, tmp_path):
        pc = PermissionChecker(
            PermissionTier.SCOPED,
            allowed_paths=[str(tmp_path)],
        )
        assert pc.check("file_read", "a1", {"path": "/etc/passwd"}) is False

    def test_tool_allowlist(self):
        pc = PermissionChecker(
            PermissionTier.SCOPED,
            allowed_tools=["file_read", "search"],
        )
        assert pc.check("file_read", "a1", {}) is True
        assert pc.check("shell", "a1", {}) is False

    def test_no_path_args_allowed_when_no_path_restriction(self):
        pc = PermissionChecker(PermissionTier.SCOPED)
        assert pc.check("search", "a1", {"pattern": "foo"}) is True

    def test_working_dir_checked(self, tmp_path):
        pc = PermissionChecker(
            PermissionTier.SCOPED,
            allowed_paths=[str(tmp_path)],
        )
        assert pc.check("shell", "a1", {"command": "ls", "working_dir": str(tmp_path)}) is True
        assert pc.check("shell", "a1", {"command": "ls", "working_dir": "/etc"}) is False
