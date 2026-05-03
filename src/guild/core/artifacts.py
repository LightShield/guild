"""Artifact management — track, version, and review agent outputs (REQ-18)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from guild.core.storage import Storage

__all__ = ["ArtifactManager"]


class ArtifactManager:
    """Tracks and versions artifacts produced by agents.

    Args:
        artifacts_dir: Directory to store artifacts.
        storage: Storage backend for metadata.
    """

    def __init__(self, artifacts_dir: Path, storage: Storage) -> None:
        self._dir = artifacts_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._storage = storage

    def save(self, task_id: str, name: str, content: str) -> Path:
        """Save an artifact for a task.

        Args:
            task_id: Task that produced this artifact.
            name: Artifact filename.
            content: Artifact content.

        Returns:
            Path to the saved artifact.
        """
        task_dir = self._dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / name
        path.write_text(content)
        return path

    def list_for_task(self, task_id: str) -> list[Path]:
        """List artifacts for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of artifact file paths.
        """
        task_dir = self._dir / task_id
        if not task_dir.is_dir():
            return []
        return sorted(task_dir.iterdir())

    def get(self, task_id: str, name: str) -> str | None:
        """Get artifact content.

        Args:
            task_id: Task identifier.
            name: Artifact filename.

        Returns:
            Content string, or None if not found.
        """
        path = self._dir / task_id / name
        if path.is_file():
            return path.read_text()
        return None
