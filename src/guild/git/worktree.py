"""Git worktree management for parallel task isolation."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["WorktreeInfo", "WorktreeManager"]

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a Guild-managed git worktree."""

    path: Path
    branch: str
    task_id: str
    created_at: str


class WorktreeManager:
    """Manages git worktrees for parallel task isolation.

    Each task gets its own worktree under .guild/worktrees/<task_id>/,
    with a dedicated branch guild/<task_id>.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    @property
    def worktrees_dir(self) -> Path:
        """Base directory for all Guild worktrees."""
        return self._repo_root / ".guild" / "worktrees"

    async def create(self, task_id: str, base_branch: str = "main") -> WorktreeInfo:
        """Create a new worktree for a task.

        Creates branch: guild/<task_id>
        Creates worktree at: .guild/worktrees/<task_id>/
        """
        branch = f"guild/{task_id}"
        worktree_path = self.worktrees_dir / task_id

        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        exit_code, output = await self._run_git(
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base_branch,
        )
        if exit_code != 0:
            raise RuntimeError(f"Failed to create worktree for task {task_id}: {output}")

        logger.info("Created worktree for task %s at %s", task_id, worktree_path)
        created_at = datetime.now(UTC).isoformat()
        return WorktreeInfo(
            path=worktree_path,
            branch=branch,
            task_id=task_id,
            created_at=created_at,
        )

    async def remove(self, task_id: str) -> None:
        """Remove a worktree after task completion."""
        worktree_path = self.worktrees_dir / task_id
        branch = f"guild/{task_id}"

        exit_code, output = await self._run_git("worktree", "remove", "--force", str(worktree_path))
        if exit_code != 0:
            raise RuntimeError(f"Failed to remove worktree for task {task_id}: {output}")

        # Delete the task branch after removing the worktree
        await self._run_git("branch", "-D", branch)
        logger.info("Removed worktree and branch for task %s", task_id)

    async def list_active(self) -> list[WorktreeInfo]:
        """List all active Guild worktrees."""
        exit_code, output = await self._run_git("worktree", "list", "--porcelain")
        if exit_code != 0:
            return []

        return self._parse_worktree_list(output)

    async def merge_to_staging(
        self, task_id: str, staging_branch: str = "guild/staging"
    ) -> tuple[bool, str]:
        """Merge task branch to staging. Returns (success, message)."""
        branch = f"guild/{task_id}"

        # Ensure staging branch exists
        await self._ensure_staging_branch(staging_branch)

        # Attempt the merge
        exit_code, output = await self._run_git(
            "merge",
            branch,
            "--no-ff",
            "-m",
            f"Merge {branch} into {staging_branch}",
            cwd=await self._staging_worktree_path(staging_branch),
        )

        if exit_code != 0:
            # Abort the failed merge
            await self._run_git(
                "merge",
                "--abort",
                cwd=await self._staging_worktree_path(staging_branch),
            )
            return False, f"Merge conflict: {output}"

        return True, f"Successfully merged {branch} into {staging_branch}"

    def _parse_worktree_list(self, output: str) -> list[WorktreeInfo]:
        """Parse porcelain worktree list output into WorktreeInfo objects."""
        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch: str | None = None

        for line in output.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line[len("worktree ") :])
            elif line.startswith("branch refs/heads/"):
                current_branch = line[len("branch refs/heads/") :]
            elif line == "" and current_path and current_branch:
                self._maybe_append_worktree(worktrees, current_path, current_branch)
                current_path = None
                current_branch = None

        # Handle last entry (porcelain output may not end with blank line)
        if current_path and current_branch:
            self._maybe_append_worktree(worktrees, current_path, current_branch)

        return worktrees

    @staticmethod
    def _maybe_append_worktree(
        worktrees: list[WorktreeInfo], path: Path, branch: str
    ) -> None:
        """Append a WorktreeInfo if the branch is a guild task (not staging)."""
        if not branch.startswith("guild/"):
            return
        task_id = branch[len("guild/") :]
        if task_id == "staging":
            return
        worktrees.append(
            WorktreeInfo(path=path, branch=branch, task_id=task_id, created_at="")
        )

    async def _ensure_staging_branch(self, staging_branch: str) -> None:
        """Ensure the staging branch and its worktree exist."""
        staging_path = self.worktrees_dir / "_staging"

        if staging_path.exists():
            return

        staging_path.parent.mkdir(parents=True, exist_ok=True)

        exit_code, _ = await self._run_git("rev-parse", "--verify", staging_branch)

        if exit_code != 0:
            # Create orphan-style staging branch from current HEAD
            exit_code, output = await self._run_git(
                "worktree",
                "add",
                "-b",
                staging_branch,
                str(staging_path),
                "HEAD",
            )
        else:
            # Branch exists, just add worktree
            exit_code, output = await self._run_git(
                "worktree",
                "add",
                str(staging_path),
                staging_branch,
            )

        if exit_code != 0:
            raise RuntimeError(f"Failed to create staging worktree: {output}")

    async def _staging_worktree_path(self, staging_branch: str) -> Path:
        """Get or create the staging worktree path."""
        staging_path = self.worktrees_dir / "_staging"
        if not staging_path.exists():
            await self._ensure_staging_branch(staging_branch)
        return staging_path

    async def _run_git(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run a git command and return (exit_code, output)."""
        cmd = ["git"] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd or self._repo_root),
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, stdout.decode().strip()
