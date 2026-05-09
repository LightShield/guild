"""Tests for task/spec.py — task specifications and lifecycle (REQ-12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from guild.storage.sqlite import Storage
from guild.task.spec import (
    TaskSpec,
    VerificationStep,
    run_verification,
    transition_task,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def storage(tmp_path: Path) -> Storage:
    """Create a connected Storage instance for testing."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path)
    await store.connect()
    yield store
    await store.close()


# ------------------------------------------------------------------
# REQ-12.1: Task definition format
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-12.1")
class TestTaskSpecFromString:
    """TaskSpec.from_string parses a plain description."""

    async def test_task_spec_from_string(self) -> None:
        """A simple string yields a TaskSpec with description only."""
        spec = TaskSpec.from_string("Implement login feature")
        assert spec.description == "Implement login feature"
        assert spec.acceptance_criteria == []
        assert spec.verification_steps == []


@pytest.mark.unit
@pytest.mark.req("REQ-12.1")
class TestTaskSpecFromToml:
    """TaskSpec.from_toml loads structured specs from TOML files."""

    async def test_task_spec_from_toml(self, tmp_path: Path) -> None:
        """A TOML file with full spec is parsed correctly."""
        toml_content = """\
description = "Build authentication module"
acceptance_criteria = ["Tests pass", "No security warnings"]

[[verification_steps]]
type = "command"
target = "pytest tests/auth/"

[[verification_steps]]
type = "file_exists"
target = "src/auth/module.py"
"""
        toml_path = tmp_path / "task.toml"
        toml_path.write_text(toml_content)

        spec = TaskSpec.from_toml(toml_path)

        assert spec.description == "Build authentication module"
        assert len(spec.acceptance_criteria) == 2
        assert "Tests pass" in spec.acceptance_criteria
        assert len(spec.verification_steps) == 2
        assert spec.verification_steps[0].type == "command"
        assert spec.verification_steps[0].target == "pytest tests/auth/"
        assert spec.verification_steps[1].type == "file_exists"


@pytest.mark.unit
@pytest.mark.req("REQ-12.1")
class TestTaskSpecFromTomlEdgeCases:
    """Edge cases for TaskSpec.from_toml loading."""

    async def test_task_spec_from_toml_with_criteria(self, tmp_path: Path) -> None:
        """TOML with acceptance_criteria but no verification_steps parses correctly."""
        toml_content = """\
description = "Refactor auth module"
acceptance_criteria = ["All tests green", "No regressions", "Code reviewed"]
"""
        toml_path = tmp_path / "criteria_only.toml"
        toml_path.write_text(toml_content)

        spec = TaskSpec.from_toml(toml_path)

        assert spec.description == "Refactor auth module"
        assert len(spec.acceptance_criteria) == 3
        assert "No regressions" in spec.acceptance_criteria
        assert spec.verification_steps == []

    async def test_task_spec_missing_fields_use_defaults(self, tmp_path: Path) -> None:
        """TOML missing description and criteria yields empty defaults."""
        # Completely empty TOML (valid but no guild-specific keys)
        toml_content = """\
"""
        toml_path = tmp_path / "empty.toml"
        toml_path.write_text(toml_content)

        spec = TaskSpec.from_toml(toml_path)

        assert spec.description == ""
        assert spec.acceptance_criteria == []
        assert spec.verification_steps == []


@pytest.mark.unit
@pytest.mark.req("REQ-12.1")
class TestTaskSpecWithCriteriaAndSteps:
    """TaskSpec constructed directly with all fields."""

    async def test_task_spec_with_criteria_and_steps(self) -> None:
        """Directly constructing a TaskSpec preserves all fields."""
        steps = [
            VerificationStep(type="command", target="make test"),
            VerificationStep(
                type="file_contains",
                target="README.md",
                expected="## Usage",
            ),
        ]
        spec = TaskSpec(
            description="Add documentation",
            acceptance_criteria=["README updated", "Examples included"],
            verification_steps=steps,
        )

        assert spec.description == "Add documentation"
        assert len(spec.acceptance_criteria) == 2
        assert len(spec.verification_steps) == 2
        assert spec.verification_steps[1].expected == "## Usage"


# ------------------------------------------------------------------
# REQ-12.2: Verification step execution
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-12.2")
class TestVerificationCommand:
    """Verification steps that run shell commands."""

    async def test_verification_command_passes_on_zero_exit(self, tmp_path: Path) -> None:
        """A command returning exit code 0 passes verification."""
        spec = TaskSpec(
            description="test",
            verification_steps=[
                VerificationStep(type="command", target="true"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True
        assert "PASS" in results[0]

    async def test_verification_command_fails_on_nonzero(self, tmp_path: Path) -> None:
        """A command returning non-zero exit code fails verification."""
        spec = TaskSpec(
            description="test",
            verification_steps=[
                VerificationStep(type="command", target="false"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert "FAIL" in results[0]


@pytest.mark.unit
@pytest.mark.req("REQ-12.2")
class TestVerificationFileExists:
    """Verification steps that check file existence."""

    async def test_verification_file_exists_passes(self, tmp_path: Path) -> None:
        """Verification passes when the target file exists."""
        target_file = tmp_path / "output.txt"
        target_file.write_text("content")

        spec = TaskSpec(
            description="test",
            verification_steps=[
                VerificationStep(type="file_exists", target="output.txt"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is True
        assert "PASS" in results[0]

    async def test_verification_file_exists_fails(self, tmp_path: Path) -> None:
        """Verification fails when the target file does not exist."""
        spec = TaskSpec(
            description="test",
            verification_steps=[
                VerificationStep(type="file_exists", target="nonexistent.txt"),
            ],
        )
        passed, results = await run_verification(spec, str(tmp_path))
        assert passed is False
        assert "FAIL" in results[0]


# ------------------------------------------------------------------
# REQ-12.5: Task status lifecycle
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-12.5")
class TestStatusTransitions:
    """Task status lifecycle enforcement."""

    async def test_valid_status_transition_allowed(self, storage: Storage) -> None:
        """A valid transition (pending -> in_progress) succeeds."""
        await storage.create_task("t1", "some task")
        result = await transition_task(storage, "t1", "in_progress")
        assert result is True

        task = await storage.get_task("t1")
        assert task["status"] == "in_progress"

    async def test_invalid_status_transition_rejected(self, storage: Storage) -> None:
        """An invalid transition (pending -> done) is rejected."""
        await storage.create_task("t2", "some task")
        result = await transition_task(storage, "t2", "done")
        assert result is False

        # Status unchanged
        task = await storage.get_task("t2")
        assert task["status"] == "pending"

    async def test_full_lifecycle_pending_to_done(self, storage: Storage) -> None:
        """A task can traverse the full happy-path lifecycle."""
        await storage.create_task("t3", "full lifecycle task")

        # pending -> in_progress
        assert await transition_task(storage, "t3", "in_progress") is True
        # in_progress -> verifying
        assert await transition_task(storage, "t3", "verifying") is True
        # verifying -> done
        assert await transition_task(storage, "t3", "done") is True

        task = await storage.get_task("t3")
        assert task["status"] == "done"

        # done -> anything should fail
        assert await transition_task(storage, "t3", "pending") is False

    async def test_invalid_transition_from_done_to_in_progress(self, storage: Storage) -> None:
        """A task in 'done' state cannot transition to 'in_progress'."""
        await storage.create_task("t-done", "completed task")
        # Move to done via valid path
        assert await transition_task(storage, "t-done", "in_progress") is True
        assert await transition_task(storage, "t-done", "done") is True

        # Attempt invalid transition back
        result = await transition_task(storage, "t-done", "in_progress")
        assert result is False

        # Status unchanged
        task = await storage.get_task("t-done")
        assert task["status"] == "done"


# ------------------------------------------------------------------
# REQ-12.3: Task decomposition tracking
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-12.3")
class TestTaskDecomposition:
    """Task decomposition into subtasks with parent tracking."""

    def test_task_node_tracks_parent(self) -> None:
        """TaskNode records its parent_id for decomposition tracking."""
        from guild.task.spec import TaskNode

        parent = TaskNode(task_id="parent-1", description="Big task")
        child = TaskNode(
            task_id="child-1",
            description="Sub-task A",
            parent_id="parent-1",
        )

        assert parent.parent_id is None
        assert child.parent_id == "parent-1"
        assert child.task_id == "child-1"
        assert child.status == "pending"

    def test_get_children_returns_subtasks(self) -> None:
        """TaskGraph.get_children returns all direct children of a parent."""
        from guild.task.spec import TaskGraph, TaskNode

        graph = TaskGraph()
        parent = TaskNode(task_id="root", description="Root task")
        child_a = TaskNode(task_id="a", description="A", parent_id="root")
        child_b = TaskNode(task_id="b", description="B", parent_id="root")
        orphan = TaskNode(task_id="c", description="C")

        graph.add_task(parent)
        graph.add_task(child_a)
        graph.add_task(child_b)
        graph.add_task(orphan)

        children = graph.get_children("root")
        child_ids = [c.task_id for c in children]
        assert "a" in child_ids
        assert "b" in child_ids
        assert "c" not in child_ids


# ------------------------------------------------------------------
# REQ-12.4: Task dependencies
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-12.4")
class TestTaskDependencies:
    """Task dependency graph — do B after A completes."""

    def test_task_graph_respects_dependencies(self) -> None:
        """Tasks with unmet dependencies are not in get_ready_tasks."""
        from guild.task.spec import TaskGraph, TaskNode

        graph = TaskGraph()
        task_a = TaskNode(task_id="a", description="First")
        task_b = TaskNode(task_id="b", description="Second", depends_on=["a"])
        graph.add_task(task_a)
        graph.add_task(task_b)

        ready = graph.get_ready_tasks()
        ready_ids = [t.task_id for t in ready]
        assert "a" in ready_ids
        assert "b" not in ready_ids

    def test_get_ready_tasks_only_when_deps_done(self) -> None:
        """After dependencies complete, dependent tasks become ready."""
        from guild.task.spec import TaskGraph, TaskNode

        graph = TaskGraph()
        task_a = TaskNode(task_id="a", description="First")
        task_b = TaskNode(task_id="b", description="Second", depends_on=["a"])
        task_c = TaskNode(task_id="c", description="Third", depends_on=["a", "b"])
        graph.add_task(task_a)
        graph.add_task(task_b)
        graph.add_task(task_c)

        # Only A is ready initially
        ready = graph.get_ready_tasks()
        assert [t.task_id for t in ready] == ["a"]

        # Complete A — B becomes ready, but not C
        graph.mark_completed("a")
        ready = graph.get_ready_tasks()
        ready_ids = [t.task_id for t in ready]
        assert "b" in ready_ids
        assert "c" not in ready_ids

        # Complete B — now C is ready
        graph.mark_completed("b")
        ready = graph.get_ready_tasks()
        ready_ids = [t.task_id for t in ready]
        assert "c" in ready_ids
