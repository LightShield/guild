"""Tests for artifact management."""

from __future__ import annotations

import pytest

from guild.artifacts.manager import ArtifactManager


@pytest.mark.unit
@pytest.mark.req("REQ-18.1")
def test_save_artifact_creates_file(tmp_path: object) -> None:
    """Saving an artifact creates the file on disk."""
    mgr = ArtifactManager(tmp_path)  # type: ignore[arg-type]
    artifact = mgr.save("task-1", "output.py", "print('hello')")

    assert artifact.task_id == "task-1"
    assert artifact.name == "output.py"
    assert artifact.version == 1
    assert artifact.path.exists()
    assert artifact.path.read_text() == "print('hello')"
    assert artifact.created_at != ""


@pytest.mark.unit
@pytest.mark.req("REQ-18.1")
def test_list_artifacts_for_task(tmp_path: object) -> None:
    """Listing artifacts returns all saved artifacts for a task."""
    mgr = ArtifactManager(tmp_path)  # type: ignore[arg-type]
    mgr.save("task-1", "file_a", "aaa")
    mgr.save("task-1", "file_b", "bbb")
    mgr.save("task-2", "file_c", "ccc")

    results = mgr.list_for_task("task-1")
    names = [(a.name, a.version) for a in results]

    assert ("file_a", 1) in names
    assert ("file_b", 1) in names
    assert len(results) == 2


@pytest.mark.unit
@pytest.mark.req("REQ-18.2")
def test_get_diff_between_versions(tmp_path: object) -> None:
    """Diff between two versions shows changes."""
    mgr = ArtifactManager(tmp_path)  # type: ignore[arg-type]
    mgr.save("task-1", "code.py", "line1\nline2\n")
    mgr.save_version("task-1", "code.py", "line1\nline2_modified\n")

    diff = mgr.get_diff("task-1", "code.py", 1, 2)

    assert "-line2" in diff
    assert "+line2_modified" in diff


@pytest.mark.unit
@pytest.mark.req("REQ-18.3")
def test_artifact_get_returns_content(tmp_path: object) -> None:
    """get() returns the content of the artifact."""
    mgr = ArtifactManager(tmp_path)  # type: ignore[arg-type]
    mgr.save("task-1", "readme", "Hello World")

    content = mgr.get("task-1", "readme")
    assert content == "Hello World"

    # Non-existent artifact returns None
    assert mgr.get("task-1", "nope") is None


@pytest.mark.unit
@pytest.mark.req("REQ-18.4")
def test_save_version_increments(tmp_path: object) -> None:
    """save_version increments the version number each time."""
    mgr = ArtifactManager(tmp_path)  # type: ignore[arg-type]
    mgr.save("task-1", "data", "v1 content")
    a2 = mgr.save_version("task-1", "data", "v2 content")
    a3 = mgr.save_version("task-1", "data", "v3 content")

    assert a2.version == 2
    assert a3.version == 3
    assert mgr.get("task-1", "data", 2) == "v2 content"
    assert mgr.get("task-1", "data", 3) == "v3 content"
    # Latest (no version) returns v3
    assert mgr.get("task-1", "data") == "v3 content"


@pytest.mark.unit
@pytest.mark.req("REQ-18.5")
def test_export_creates_directory(tmp_path: object) -> None:
    """Export copies all task artifacts to the output directory."""
    mgr = ArtifactManager(tmp_path / "artifacts")  # type: ignore[arg-type]
    mgr.save("task-1", "file_a", "aaa")
    mgr.save_version("task-1", "file_a", "aaa_v2")

    export_dir = tmp_path / "export"  # type: ignore[operator]
    result = mgr.export("task-1", export_dir)

    assert result == export_dir
    assert export_dir.exists()
    exported_files = list(export_dir.iterdir())
    assert len(exported_files) == 2


# ======================================================================
# Artifacts manager edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-22.1")
class TestArtifactsEdgeCases:
    """Cover artifact manager edge cases."""

    def test_latest_version_no_task_dir(self, tmp_path: Path) -> None:
        """_latest_version returns 0 when task dir doesn\'t exist."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        assert mgr._latest_version("nonexistent-task", "file") == 0

    def test_list_for_task_no_dir(self, tmp_path: Path) -> None:
        """list_for_task returns empty when task dir missing."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        result = mgr.list_for_task("no-such-task")
        assert result == []

    def test_list_for_task_skips_non_versioned(self, tmp_path: Path) -> None:
        """list_for_task skips files that don\'t match the versioning pattern."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        task_dir = tmp_path / "artifacts" / "task-1"
        task_dir.mkdir(parents=True)
        (task_dir / "not_versioned.txt").write_text("hello")
        (task_dir / "result.v1").write_text("v1 content")
        result = mgr.list_for_task("task-1")
        assert len(result) == 1
        assert result[0].name == "result"

    def test_get_nonexistent_version(self, tmp_path: Path) -> None:
        """get() returns None for non-existent version."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        result = mgr.get("task-x", "file", version=99)
        assert result is None

    def test_export_empty_task(self, tmp_path: Path) -> None:
        """export() works even when task has no artifacts."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        output_dir = tmp_path / "export"
        result = mgr.export("empty-task", output_dir)
        assert result == output_dir
        assert output_dir.exists()

    def test_export_copies_files(self, tmp_path: Path) -> None:
        """export() copies all artifacts to output directory."""
        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-1", "code", "def main(): pass")
        mgr.save_version("task-1", "code", "def main(): return 42")
        output_dir = tmp_path / "export"
        mgr.export("task-1", output_dir)
        assert (output_dir / "code.v1").exists()
        assert (output_dir / "code.v2").exists()
