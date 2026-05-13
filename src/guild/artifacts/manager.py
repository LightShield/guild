"""Artifact management: collection, versioning, diff, and export."""

from __future__ import annotations

import difflib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003

__all__ = ["Artifact", "ArtifactManager"]

logger = logging.getLogger(__name__)


@dataclass
class Artifact:
    """A versioned output artifact tied to a task."""

    task_id: str
    name: str
    path: Path
    version: int = 1
    created_at: str = field(default_factory=lambda: "")


class ArtifactManager:
    """Manages artifact storage, versioning, diffs, and export."""

    def __init__(self, artifacts_dir: Path) -> None:
        self._dir = artifacts_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task_id: str) -> Path:
        return self._dir / task_id

    def _version_path(self, task_id: str, name: str, version: int) -> Path:
        return self._task_dir(task_id) / f"{name}.v{version}"

    def _latest_version(self, task_id: str, name: str) -> int:
        """Find the highest version number for a given artifact name."""
        task_dir = self._task_dir(task_id)
        if not task_dir.exists():
            return 0
        prefix = f"{name}.v"
        versions = [
            int(p.name[len(prefix) :])
            for p in task_dir.iterdir()
            if p.name.startswith(prefix) and p.name[len(prefix) :].isdigit()
        ]
        return max(versions) if versions else 0

    def _status_path(self, task_id: str) -> Path:
        """Return path to the status JSON file for a task."""
        return self._task_dir(task_id) / ".status.json"

    def _load_status(self, task_id: str) -> dict[str, str]:
        """Load the status dict for a task (name -> 'pending'|'accepted')."""
        path = self._status_path(task_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def _save_status(self, task_id: str, status: dict[str, str]) -> None:
        """Persist the status dict for a task."""
        path = self._status_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status), encoding="utf-8")

    def save(self, task_id: str, name: str, content: str) -> Artifact:
        """Save an artifact (version 1). Marks as pending."""
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        path = self._version_path(task_id, name, 1)
        path.write_text(content, encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        status = self._load_status(task_id)
        status[name] = "pending"
        self._save_status(task_id, status)
        logger.debug("Saved artifact %s/%s v1", task_id, name)
        return Artifact(task_id=task_id, name=name, path=path, version=1, created_at=now)

    def save_version(self, task_id: str, name: str, content: str) -> Artifact:
        """Save a new version (auto-increment version number)."""
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        latest = self._latest_version(task_id, name)
        new_version = latest + 1
        path = self._version_path(task_id, name, new_version)
        path.write_text(content, encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        logger.debug("Saved artifact %s/%s v%d", task_id, name, new_version)
        return Artifact(
            task_id=task_id,
            name=name,
            path=path,
            version=new_version,
            created_at=now,
        )

    def list_for_task(self, task_id: str) -> list[Artifact]:
        """List all artifacts (all versions) for a task."""
        task_dir = self._task_dir(task_id)
        if not task_dir.exists():
            return []
        artifacts: list[Artifact] = []
        for p in sorted(task_dir.iterdir()):
            parts = p.name.rsplit(".v", 1)
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            name, ver = parts[0], int(parts[1])
            artifacts.append(Artifact(task_id=task_id, name=name, path=p, version=ver))
        return artifacts

    def get(self, task_id: str, name: str, version: int | None = None) -> str | None:
        """Get artifact content. Returns latest version if version is None."""
        if version is None:
            version = self._latest_version(task_id, name)
        if version == 0:
            return None
        path = self._version_path(task_id, name, version)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def get_diff(self, task_id: str, name: str, v1: int, v2: int) -> str:
        """Get unified diff between two versions of an artifact."""
        content_v1 = self.get(task_id, name, v1) or ""
        content_v2 = self.get(task_id, name, v2) or ""
        diff_lines = difflib.unified_diff(
            content_v1.splitlines(keepends=True),
            content_v2.splitlines(keepends=True),
            fromfile=f"{name}.v{v1}",
            tofile=f"{name}.v{v2}",
        )
        return "".join(diff_lines)

    def export(self, task_id: str, output_path: Path) -> Path:
        """Export all artifacts for a task to a directory."""
        task_dir = self._task_dir(task_id)
        output_path.mkdir(parents=True, exist_ok=True)
        if task_dir.exists():
            for p in task_dir.iterdir():
                if p.name == ".status.json":
                    continue
                shutil.copy2(p, output_path / p.name)
        logger.info("Exported artifacts for task %s to %s", task_id, output_path)
        return output_path

    # ------------------------------------------------------------------
    # Review gate: accept / reject / edit (REQ-18.3)
    # ------------------------------------------------------------------

    def accept(self, task_id: str, name: str, project_dir: Path | None = None) -> None:
        """Accept a pending artifact, marking it as final.

        When *project_dir* is provided, the latest version of the artifact
        is also copied into the project working tree at ``project_dir/name``.
        """
        status = self._load_status(task_id)
        if name not in status:
            msg = f"Artifact '{name}' not found for task '{task_id}'"
            raise KeyError(msg)
        status[name] = "accepted"
        self._save_status(task_id, status)

        if project_dir is not None:
            content = self.get(task_id, name)
            if content is not None:
                target = project_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                logger.debug("Copied artifact %s/%s to %s", task_id, name, target)

        logger.debug("Accepted artifact %s/%s", task_id, name)

    def reject(self, task_id: str, name: str) -> None:
        """Reject a pending artifact, removing it entirely."""
        status = self._load_status(task_id)
        if name not in status:
            msg = f"Artifact '{name}' not found for task '{task_id}'"
            raise KeyError(msg)
        del status[name]
        self._save_status(task_id, status)
        task_dir = self._task_dir(task_id)
        if task_dir.exists():  # pragma: no branch — task_dir exists if status loaded
            prefix = f"{name}.v"
            for p in task_dir.iterdir():
                if p.name.startswith(prefix) and p.name[len(prefix):].isdigit():
                    p.unlink()
        logger.debug("Rejected artifact %s/%s", task_id, name)

    def edit(self, task_id: str, name: str, content: str) -> Artifact:
        """Edit an artifact with new content and auto-accept it."""
        status = self._load_status(task_id)
        if name not in status:
            msg = f"Artifact '{name}' not found for task '{task_id}'"
            raise KeyError(msg)
        artifact = self.save_version(task_id, name, content)
        status[name] = "accepted"
        self._save_status(task_id, status)
        logger.debug("Edited and accepted artifact %s/%s", task_id, name)
        return artifact

    def list_pending(self, task_id: str) -> list[Artifact]:
        """List artifacts awaiting review (status == 'pending')."""
        return self._list_by_status(task_id, "pending")

    def list_accepted(self, task_id: str) -> list[Artifact]:
        """List accepted artifacts (status == 'accepted')."""
        return self._list_by_status(task_id, "accepted")

    def _list_by_status(
        self, task_id: str, target_status: str
    ) -> list[Artifact]:
        """Return artifacts matching the given status."""
        status = self._load_status(task_id)
        artifacts: list[Artifact] = []
        for name, st in status.items():
            if st != target_status:
                continue
            version = self._latest_version(task_id, name)
            path = self._version_path(task_id, name, version)
            artifacts.append(
                Artifact(task_id=task_id, name=name, path=path, version=version)
            )
        return artifacts
