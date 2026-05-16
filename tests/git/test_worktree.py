"""Tests for guild.git.worktree — worktree isolation for tasks."""

import asyncio
from pathlib import Path

import pytest

from guild.git.worktree import BRANCH_PREFIX, STAGING_BRANCH_SUFFIX, WorktreeManager


async def _init_test_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()

    async def run(cmd: str) -> None:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}\n{stdout.decode()}")

    await run("git init -b main")
    await run("git config user.email 'test@test.com'")
    await run("git config user.name 'Test'")
    # Create an initial commit so branches can be created
    (repo / "README.md").write_text("# Test Repo\n")
    await run("git add README.md")
    await run("git commit -m 'Initial commit'")

    return repo


@pytest.mark.unit
class TestCreateWorktree:
    """Test worktree creation for task isolation."""

    async def test_create_worktree_makes_directory(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-001")

        assert info.path.exists()
        assert info.path.is_dir()
        assert info.task_id == "task-001"

    async def test_create_worktree_creates_branch(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-002")

        assert info.branch == "guild/task-002"
        # Verify the branch exists in git
        exit_code, _ = await manager._run_git("rev-parse", "--verify", "guild/task-002")
        assert exit_code == 0

    async def test_create_worktree_path_under_guild_dir(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-003")

        expected = repo / ".guild" / "worktrees" / "task-003"
        assert info.path == expected

    async def test_create_worktree_has_timestamp(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-004")

        assert info.created_at != ""
        assert "T" in info.created_at  # ISO format


@pytest.mark.unit
class TestWorktreeBranchNaming:
    """Branch naming convention for worktrees."""

    async def test_create_worktree_branch_naming(self, tmp_path: Path) -> None:
        """Worktree branch follows the guild/<task_id> convention."""
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        # Test with various task ID formats
        info = await manager.create("fix-auth-bug-123")

        assert info.branch == "guild/fix-auth-bug-123"
        assert info.task_id == "fix-auth-bug-123"
        # Verify the actual git branch exists
        exit_code, _ = await manager._run_git("rev-parse", "--verify", "guild/fix-auth-bug-123")
        assert exit_code == 0


@pytest.mark.unit
class TestRemoveWorktree:
    """Test worktree cleanup after task completion."""

    async def test_remove_worktree_cleans_up(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-rm-001")
        assert info.path.exists()

        await manager.remove("task-rm-001")

        # Worktree directory should be gone
        assert not info.path.exists()
        # Branch should also be deleted
        exit_code, _ = await manager._run_git("rev-parse", "--verify", "guild/task-rm-001")
        assert exit_code != 0


@pytest.mark.unit
class TestListActiveWorktrees:
    """Test listing active Guild worktrees."""

    async def test_list_active_worktrees(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        await manager.create("task-list-001")
        await manager.create("task-list-002")

        active = await manager.list_active()

        task_ids = [w.task_id for w in active]
        assert "task-list-001" in task_ids
        assert "task-list-002" in task_ids

    async def test_list_active_excludes_removed(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        await manager.create("task-keep")
        await manager.create("task-gone")
        await manager.remove("task-gone")

        active = await manager.list_active()

        task_ids = [w.task_id for w in active]
        assert "task-keep" in task_ids
        assert "task-gone" not in task_ids

    async def test_list_active_empty_when_none(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        active = await manager.list_active()

        # Should not include the main worktree (not guild-managed)
        assert len(active) == 0


@pytest.mark.unit
class TestMergeToStaging:
    """Test merging task branches to staging area."""

    async def test_merge_to_staging_succeeds(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        info = await manager.create("task-merge-001")
        # Make a change in the task worktree
        (info.path / "new_file.txt").write_text("task work\n")
        await manager._run_git("add", "new_file.txt", cwd=info.path)
        await manager._run_git("commit", "-m", "task work", cwd=info.path)

        success, message = await manager.merge_to_staging("task-merge-001")

        assert success is True
        assert "Successfully merged" in message

    async def test_merge_to_staging_reports_conflicts(self, tmp_path: Path) -> None:
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        # Create two tasks that modify the same file
        info_a = await manager.create("task-conflict-a")
        (info_a.path / "shared.txt").write_text("version A\n")
        await manager._run_git("add", "shared.txt", cwd=info_a.path)
        await manager._run_git("commit", "-m", "A changes shared", cwd=info_a.path)

        info_b = await manager.create("task-conflict-b")
        (info_b.path / "shared.txt").write_text("version B\n")
        await manager._run_git("add", "shared.txt", cwd=info_b.path)
        await manager._run_git("commit", "-m", "B changes shared", cwd=info_b.path)

        # Merge A first — should succeed
        success_a, _ = await manager.merge_to_staging("task-conflict-a")
        assert success_a is True

        # Merge B — should conflict with A's changes
        success_b, message_b = await manager.merge_to_staging("task-conflict-b")
        assert success_b is False
        assert "conflict" in message_b.lower()


# ---------------------------------------------------------------------------
# Tests: _create_worktree with existing branch (line 182)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateWorktreeExistingBranch:
    """Test _create_worktree when the branch already exists (line 182)."""

    async def test_create_worktree_with_existing_branch(self, tmp_path: Path) -> None:
        """_create_worktree with branch_exists=True uses 'worktree add' without -b."""
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        staging_branch = f"{BRANCH_PREFIX}{STAGING_BRANCH_SUFFIX}"

        # Create the staging branch manually first
        await manager._run_git("branch", staging_branch)

        # Now call _create_worktree with branch_exists=True
        staging_path = manager.worktrees_dir / "_test_existing"
        staging_path.parent.mkdir(parents=True, exist_ok=True)

        await manager._create_worktree(staging_path, staging_branch, branch_exists=True)

        assert staging_path.exists()
        assert staging_path.is_dir()


# ---------------------------------------------------------------------------
# Tests: _create_worktree failure raises RuntimeError (line 188)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateWorktreeFailure:
    """Test _create_worktree raises RuntimeError on git failure (line 188)."""

    async def test_create_worktree_raises_on_invalid_branch(self, tmp_path: Path) -> None:
        """_create_worktree raises RuntimeError when git worktree add fails."""
        repo = await _init_test_repo(tmp_path)
        manager = WorktreeManager(repo)

        worktree_path = manager.worktrees_dir / "bad_worktree"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # branch_exists=True but the branch does not actually exist in git
        # This will cause `git worktree add <path> <branch>` to fail
        with pytest.raises(RuntimeError, match="Failed to create staging worktree"):
            await manager._create_worktree(worktree_path, "nonexistent-branch", branch_exists=True)


# ======================================================================
# Worktree _parse_worktree_list (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestWorktreeParseList:
    """Cover worktree list parsing edge cases."""

    def test_parse_empty_output(self) -> None:
        """Empty output produces empty list."""
        mgr = WorktreeManager(repo_root=Path("/tmp"))
        result = mgr._parse_worktree_list("")
        assert result == []

    def test_parse_guild_worktrees(self) -> None:
        """Parses guild-managed worktrees from porcelain output."""
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
        mgr = WorktreeManager(repo_root=Path("/tmp"))
        output = (
            "worktree /repo/.guild/worktrees/_staging\n" "branch refs/heads/guild/staging\n" "\n"
        )
        result = mgr._parse_worktree_list(output)
        assert result == []

    def test_parse_no_trailing_newline(self) -> None:
        """Handles last entry without trailing blank line."""
        mgr = WorktreeManager(repo_root=Path("/tmp"))
        # No blank line after last entry
        output = "worktree /repo/.guild/worktrees/task-2\n" "branch refs/heads/guild/task-2\n"
        result = mgr._parse_worktree_list(output)
        assert len(result) == 1
        assert result[0].task_id == "task-2"

    def test_parse_non_guild_branches_excluded(self) -> None:
        """Non-guild branches are excluded from results."""
        mgr = WorktreeManager(repo_root=Path("/tmp"))
        output = "worktree /repo\n" "branch refs/heads/feature/my-feature\n" "\n"
        result = mgr._parse_worktree_list(output)
        assert result == []


# ======================================================================
# Worktree operations with mocked git (from coverage gaps)
# ======================================================================


@pytest.mark.unit
class TestWorktreeOperations:
    """Test worktree operations with mocked git."""

    async def test_create_fails_raises(self, tmp_path: Path) -> None:
        """create() raises RuntimeError when git fails."""
        from unittest.mock import patch

        mgr = WorktreeManager(repo_root=tmp_path)
        with (
            patch.object(mgr, "_run_git", return_value=(1, "fatal: error")),
            pytest.raises(RuntimeError, match="Failed to create"),
        ):
            await mgr.create("task-1")

    async def test_remove_fails_raises(self, tmp_path: Path) -> None:
        """remove() raises RuntimeError when git fails."""
        from unittest.mock import patch

        mgr = WorktreeManager(repo_root=tmp_path)
        with (
            patch.object(mgr, "_run_git", return_value=(1, "fatal: error")),
            pytest.raises(RuntimeError, match="Failed to remove"),
        ):
            await mgr.remove("task-1")

    async def test_list_active_on_git_failure(self, tmp_path: Path) -> None:
        """list_active() returns empty list when git fails."""
        from unittest.mock import patch

        mgr = WorktreeManager(repo_root=tmp_path)
        with patch.object(mgr, "_run_git", return_value=(1, "error")):
            result = await mgr.list_active()
            assert result == []

    async def test_ensure_staging_existing_path(self, tmp_path: Path) -> None:
        """_ensure_staging_branch returns early if staging path exists."""
        from unittest.mock import patch

        mgr = WorktreeManager(repo_root=tmp_path)
        staging_path = mgr.worktrees_dir / "_staging"
        staging_path.mkdir(parents=True)
        # Should return without calling git
        with patch.object(mgr, "_run_git") as mock_git:
            await mgr._ensure_staging_branch("guild/staging")
            mock_git.assert_not_called()

    async def test_staging_worktree_path_creates_if_missing(self, tmp_path: Path) -> None:
        """_staging_worktree_path calls _ensure_staging_branch when missing."""
        from unittest.mock import AsyncMock, patch

        mgr = WorktreeManager(repo_root=tmp_path)
        with patch.object(mgr, "_ensure_staging_branch", new_callable=AsyncMock) as mock_ensure:
            await mgr._staging_worktree_path("guild/staging")
            mock_ensure.assert_called_once()


@pytest.mark.unit
class TestRunGitTimeout:
    """Cover the timeout branch in _run_git (lines 207-210)."""

    async def test_run_git_returns_error_on_timeout(self, tmp_path: Path) -> None:
        """_run_git returns (1, 'timed out') when git command exceeds timeout."""
        from unittest.mock import AsyncMock, patch

        mgr = WorktreeManager(repo_root=tmp_path)

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError("timed out"))
        mock_proc.kill = AsyncMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            code, output = await mgr._run_git("status")

        assert code == 1
        assert "timed out" in output
