"""Tests for agent/rollback.py — try-test-rollback (REQ-06.11)."""

from __future__ import annotations

import pytest

from guild.agent.rollback import RollbackContext, try_with_rollback


@pytest.mark.unit
@pytest.mark.req("REQ-06.11")
class TestRollbackContext:
    """RollbackContext captures and restores file state."""

    def test_capture_existing_file_saves_content(self, tmp_path: object) -> None:
        """Capturing an existing file stores its content."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "hello.txt"
        f.write_text("original content")

        ctx = RollbackContext()
        ctx.capture(str(f))

        assert str(f) in ctx.modified_paths
        # Internal snapshot should have the content
        snapshot = ctx._snapshots[str(f)]
        assert snapshot.content == "original content"

    def test_capture_nonexistent_file_records_none(self, tmp_path: object) -> None:
        """Capturing a nonexistent file records None content."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "does_not_exist.txt"

        ctx = RollbackContext()
        ctx.capture(str(f))

        snapshot = ctx._snapshots[str(f)]
        assert snapshot.content is None

    def test_rollback_restores_modified_file(self, tmp_path: object) -> None:
        """Rollback restores a modified file to its captured state."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "data.txt"
        f.write_text("before")

        ctx = RollbackContext()
        ctx.capture(str(f))

        # Simulate modification
        f.write_text("after")
        assert f.read_text() == "after"

        ctx.rollback()
        assert f.read_text() == "before"

    def test_rollback_deletes_newly_created_file(self, tmp_path: object) -> None:
        """Rollback deletes a file that didn't exist when captured."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "new_file.txt"

        ctx = RollbackContext()
        ctx.capture(str(f))

        # Simulate creation
        f.write_text("created after capture")
        assert f.exists()

        ctx.rollback()
        assert not f.exists()

    def test_rollback_returns_rolled_back_paths(self, tmp_path: object) -> None:
        """rollback() returns list of all paths that were rolled back."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f1 = tmp / "a.txt"
        f2 = tmp / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")

        ctx = RollbackContext()
        ctx.capture(str(f1))
        ctx.capture(str(f2))

        # Modify both
        f1.write_text("modified")
        f2.write_text("modified")

        rolled = ctx.rollback()
        assert str(f1) in rolled
        assert str(f2) in rolled
        assert len(rolled) == 2

    def test_discard_clears_snapshots(self, tmp_path: object) -> None:
        """discard() removes all snapshots without restoring."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "keep.txt"
        f.write_text("original")

        ctx = RollbackContext()
        ctx.capture(str(f))

        f.write_text("changed")
        ctx.discard()

        assert ctx.modified_paths == []
        # File retains the new content
        assert f.read_text() == "changed"


@pytest.mark.unit
@pytest.mark.req("REQ-06.11")
class TestTryWithRollback:
    """try_with_rollback wraps execute-verify-rollback pattern."""

    async def test_try_with_rollback_keeps_changes_on_success(self, tmp_path: object) -> None:
        """On successful verification, changes are kept."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "file.txt"
        f.write_text("initial")

        async def execute():
            f.write_text("new content")
            return "done"

        async def verify():
            return True

        success, result = await try_with_rollback(execute, verify, [str(f)])

        assert success is True
        assert result == "done"
        assert f.read_text() == "new content"

    async def test_try_with_rollback_reverts_on_verification_failure(
        self, tmp_path: object
    ) -> None:
        """On failed verification, changes are rolled back."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f = tmp / "file.txt"
        f.write_text("original")

        async def execute():
            f.write_text("bad change")
            return "result"

        async def verify():
            return False

        success, result = await try_with_rollback(execute, verify, [str(f)])

        assert success is False
        assert result is None
        assert f.read_text() == "original"

    async def test_try_with_rollback_handles_multiple_files(self, tmp_path: object) -> None:
        """Multiple files are all rolled back on failure."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        f1 = tmp / "one.txt"
        f2 = tmp / "two.txt"
        f3 = tmp / "three.txt"
        f1.write_text("1")
        f2.write_text("2")
        # f3 does not exist initially

        async def execute():
            f1.write_text("X")
            f2.write_text("Y")
            f3.write_text("Z")
            return "multi"

        async def verify():
            return False

        success, result = await try_with_rollback(execute, verify, [str(f1), str(f2), str(f3)])

        assert success is False
        assert result is None
        assert f1.read_text() == "1"
        assert f2.read_text() == "2"
        assert not f3.exists()
