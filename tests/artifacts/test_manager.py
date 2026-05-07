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
