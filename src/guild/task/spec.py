"""Task specification format and verification execution (REQ-12).

Provides structured task definitions with acceptance criteria,
verification steps, and status lifecycle enforcement.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.storage.sqlite import Storage

__all__ = [
    "TaskStatus",
    "VALID_TRANSITIONS",
    "TaskGraph",
    "TaskNode",
    "TaskSpec",
    "VerificationStep",
    "run_verification",
    "transition_task",
]


class TaskStatus(str, Enum):
    """Canonical task status values used throughout Guild."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    PAUSED = "paused"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    VERIFYING = "verifying"
    DONE = "done"


logger = logging.getLogger(__name__)

# REQ-12.5: Valid status transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    TaskStatus.PENDING: [TaskStatus.IN_PROGRESS],
    TaskStatus.IN_PROGRESS: [
        TaskStatus.VERIFYING,
        TaskStatus.DONE,
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
    ],
    TaskStatus.VERIFYING: [TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.IN_PROGRESS],
    TaskStatus.DONE: [],
    TaskStatus.FAILED: [TaskStatus.PENDING],
    TaskStatus.BLOCKED: [TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
}


@dataclass
class TaskNode:
    """A node in a task decomposition tree (REQ-12.3).

    Attributes:
        task_id: Unique identifier for this task node.
        description: Human-readable description.
        parent_id: ID of parent task (None for root tasks).
        depends_on: List of task IDs that must complete before this.
        status: Current status (pending, completed, failed).
    """

    task_id: str
    description: str
    parent_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING


class TaskGraph:
    """DAG of task dependencies (REQ-12.4).

    Manages a collection of TaskNodes and resolves which tasks
    are ready to execute based on dependency completion status.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}

    def add_task(self, node: TaskNode) -> None:
        """Add a task node to the graph."""
        self._nodes[node.task_id] = node

    def get_ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed.

        A task is ready when:
        - Its status is "pending"
        - All task_ids in its depends_on have status "completed"
        """
        ready: list[TaskNode] = []
        for node in self._nodes.values():
            if node.status != TaskStatus.PENDING:
                continue
            if all(
                self._nodes[dep].status == TaskStatus.COMPLETED
                for dep in node.depends_on
                if dep in self._nodes
            ):
                ready.append(node)
        return ready

    def mark_completed(self, task_id: str) -> None:
        """Mark a task as completed."""
        if task_id in self._nodes:
            self._nodes[task_id].status = TaskStatus.COMPLETED

    def get_children(self, task_id: str) -> list[TaskNode]:
        """Return tasks whose parent_id matches the given task_id."""
        return [node for node in self._nodes.values() if node.parent_id == task_id]


@dataclass
class VerificationStep:
    """A step to verify task completion (REQ-12.2).

    Attributes:
        type: One of "command", "file_exists", "file_contains", "custom".
        target: Command to run, file path, or custom check identifier.
        expected: Expected output or content (optional).
    """

    type: str
    target: str
    expected: str | None = None


@dataclass
class TaskSpec:
    """Structured task definition with acceptance criteria (REQ-12.1).

    Attributes:
        description: Human-readable task description.
        acceptance_criteria: List of criteria that define "done".
        verification_steps: Automated checks to validate completion.
    """

    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_steps: list[VerificationStep] = field(default_factory=list)

    @classmethod
    def from_string(cls, description: str) -> TaskSpec:
        """Parse a simple string into a TaskSpec (no criteria)."""
        return cls(description=description)

    @classmethod
    def from_toml(cls, path: Path) -> TaskSpec:
        """Load a task spec from a TOML file.

        Expected TOML format::

            description = "Implement feature X"
            acceptance_criteria = ["Tests pass", "No lint errors"]

            [[verification_steps]]
            type = "command"
            target = "pytest tests/"
            expected = ""

            [[verification_steps]]
            type = "file_exists"
            target = "src/module.py"
        """
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)

        description = data.get("description", "")
        criteria = data.get("acceptance_criteria", [])

        steps: list[VerificationStep] = []
        for step_data in data.get("verification_steps", []):
            steps.append(
                VerificationStep(
                    type=step_data.get("type", "custom"),
                    target=step_data.get("target", ""),
                    expected=step_data.get("expected"),
                )
            )

        return cls(
            description=description,
            acceptance_criteria=criteria,
            verification_steps=steps,
        )


async def run_verification(
    spec: TaskSpec,
    working_dir: str,
) -> tuple[bool, list[str]]:
    """Run all verification steps for a task spec (REQ-12.2).

    Returns a tuple of (all_passed, results) where results contains
    a description of each step outcome.
    """
    if not spec.verification_steps:
        return True, ["No verification steps defined"]

    results: list[str] = []
    all_passed = True

    for step in spec.verification_steps:
        passed, message = await _run_single_step(step, working_dir)
        results.append(message)
        if not passed:
            all_passed = False

    return all_passed, results


async def _run_single_step(
    step: VerificationStep,
    working_dir: str,
) -> tuple[bool, str]:
    """Execute a single verification step and return (passed, message)."""
    if step.type == "command":
        return await _verify_command(step, working_dir)
    if step.type == "file_exists":
        return _verify_file_exists(step, working_dir)
    if step.type == "file_contains":
        return _verify_file_contains(step, working_dir)
    return False, f"Unknown verification type: {step.type}"


async def _verify_command(
    step: VerificationStep,
    working_dir: str,
) -> tuple[bool, str]:
    """Run a shell command and check exit code (REQ-12.2)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            step.target,
            cwd=working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        passed = proc.returncode == 0

        if passed:
            msg = f"PASS: command '{step.target}' exited 0"
        else:
            output = (stderr or stdout or b"").decode().strip()[:200]
            msg = f"FAIL: command '{step.target}' " f"exited {proc.returncode}: {output}"
        return passed, msg
    except OSError as exc:
        return False, f"FAIL: command '{step.target}' error: {exc}"


def _verify_file_exists(
    step: VerificationStep,
    working_dir: str,
) -> tuple[bool, str]:
    """Check that a file exists at the given path."""
    target_path = Path(working_dir) / step.target
    if target_path.is_file():
        return True, f"PASS: file exists '{step.target}'"
    return False, f"FAIL: file not found '{step.target}'"


def _verify_file_contains(
    step: VerificationStep,
    working_dir: str,
) -> tuple[bool, str]:
    """Check that a file contains expected content."""
    target_path = Path(working_dir) / step.target
    if not target_path.is_file():
        return False, f"FAIL: file not found '{step.target}'"

    content = target_path.read_text()
    if step.expected and step.expected in content:
        return True, f"PASS: file '{step.target}' contains expected text"
    return False, f"FAIL: file '{step.target}' missing expected text"


async def transition_task(
    storage: Storage,
    task_id: str,
    new_status: str,
) -> bool:
    """Transition task status with lifecycle validation (REQ-12.5).

    Returns True if the transition was valid and applied, False otherwise.
    """
    task = await storage.get_task(task_id)
    if task is None:
        logger.warning("transition_task: task %s not found", task_id)
        return False

    current_status = task["status"]
    allowed = VALID_TRANSITIONS.get(current_status, [])

    if new_status not in allowed:
        logger.warning(
            "Invalid transition: %s -> %s (allowed: %s)",
            current_status,
            new_status,
            allowed,
        )
        return False

    await storage.update_task(task_id, status=new_status)
    return True
