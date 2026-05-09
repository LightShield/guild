"""Try-test-rollback for impactful decisions (REQ-06.11).

Provides file-level snapshotting and rollback so agents can try an approach,
verify it, and revert if verification fails — without git worktrees.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Awaitable, Callable

__all__ = ["FileSnapshot", "RollbackContext", "try_with_rollback"]

logger = logging.getLogger(__name__)


@dataclass
class FileSnapshot:
    """Captured state of a single file before modification."""

    path: Path
    content: str | None  # None means file didn't exist (delete on rollback)


class RollbackContext:
    """Tracks file changes for potential rollback."""

    def __init__(self) -> None:
        self._snapshots: dict[str, FileSnapshot] = {}

    def capture(self, path: str) -> None:
        """Capture current state of a file before modification."""
        p = Path(path)
        if p.exists():
            self._snapshots[path] = FileSnapshot(path=p, content=p.read_text())
        else:
            self._snapshots[path] = FileSnapshot(path=p, content=None)

    def rollback(self) -> list[str]:
        """Restore all captured files to their original state.

        Returns list of rolled-back paths.
        """
        rolled_back: list[str] = []
        for path, snapshot in self._snapshots.items():
            if snapshot.content is None:
                # File didn't exist before — delete it if it now exists
                if snapshot.path.exists():
                    snapshot.path.unlink()
                    logger.debug("Rolled back (deleted): %s", path)
            else:
                # Restore original content
                snapshot.path.parent.mkdir(parents=True, exist_ok=True)
                snapshot.path.write_text(snapshot.content)
                logger.debug("Rolled back (restored): %s", path)
            rolled_back.append(path)
        self._snapshots.clear()
        return rolled_back

    def discard(self) -> None:
        """Discard snapshots (changes are accepted)."""
        self._snapshots.clear()

    @property
    def modified_paths(self) -> list[str]:
        """List of paths that have been captured."""
        return list(self._snapshots.keys())


async def try_with_rollback(
    execute_fn: Callable[[], Awaitable[Any]],
    verify_fn: Callable[[], Awaitable[bool]],
    paths: list[str],
) -> tuple[bool, Any]:
    """Try an operation, verify it, rollback if verification fails.

    Args:
        execute_fn: Async callable that performs the operation.
        verify_fn: Async callable returning True if result is acceptable.
        paths: File paths to snapshot before execution.

    Returns:
        Tuple of (success, result). On failure result is None.
    """
    ctx = RollbackContext()
    for path in paths:
        ctx.capture(path)

    result = await execute_fn()

    if await verify_fn():
        ctx.discard()
        return True, result

    ctx.rollback()
    return False, None
