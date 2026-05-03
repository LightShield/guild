"""Tests for runtime permission switching (REQ-03.5)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.models import PermissionTier
from guild.core.permissions import PermissionChecker


class TestRuntimePermissionSwitch:
    """REQ-03.5: Permission level switchable at runtime without restart."""

    def test_switch_nothing_to_autopilot(self):
        checker = PermissionChecker(PermissionTier.NOTHING)
        assert checker.check("shell", "a1", {"command": "ls"}) is False

        checker.set_tier(PermissionTier.AUTOPILOT)
        assert checker.check("shell", "a1", {"command": "ls"}) is True

    def test_switch_autopilot_to_nothing(self):
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        assert checker.check("shell", "a1", {"command": "ls"}) is True

        checker.set_tier(PermissionTier.NOTHING)
        assert checker.check("shell", "a1", {"command": "ls"}) is False

    def test_switch_to_scoped(self, tmp_path):
        checker = PermissionChecker(PermissionTier.AUTOPILOT)
        checker.set_tier(PermissionTier.SCOPED, allowed_paths=[str(tmp_path)])
        assert checker.check("file_read", "a1", {"path": str(tmp_path / "x")}) is True
        assert checker.check("file_read", "a1", {"path": "/etc/passwd"}) is False

    def test_switch_clears_session_approvals(self):
        """Switching tiers should clear any session-level approvals."""
        checker = PermissionChecker(
            PermissionTier.ASK,
            prompt_fn=lambda *_: True,
        )
        checker._session_approvals.add("file_read")
        checker.set_tier(PermissionTier.SCOPED)
        assert len(checker._session_approvals) == 0

    def test_get_tier(self):
        checker = PermissionChecker(PermissionTier.ASK)
        assert checker.get_tier() == PermissionTier.ASK
        checker.set_tier(PermissionTier.AUTOPILOT)
        assert checker.get_tier() == PermissionTier.AUTOPILOT
