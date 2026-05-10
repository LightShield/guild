"""Task specification and lifecycle management (REQ-12)."""

from guild.task.spec import TaskSpec, TaskStatus, VerificationStep, run_verification

__all__ = ["TaskSpec", "TaskStatus", "VerificationStep", "run_verification"]
