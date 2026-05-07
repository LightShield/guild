"""Configurable branching and merge policy for Guild projects."""

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["BranchPolicy", "MergeApproval"]


class MergeApproval(str, Enum):
    """Merge approval strategy."""

    AUTO = "auto"  # merge if tests pass
    REVIEW = "review"  # always require user review
    STAGING = "staging"  # merge to staging freely, main requires review


@dataclass
class BranchPolicy:
    """Configurable branching and merge policy."""

    protected_branches: list[str] = field(default_factory=lambda: ["main", "master"])
    staging_branch: str = "guild/staging"
    merge_approval: MergeApproval = MergeApproval.STAGING
    auto_merge_on_tests_pass: bool = False
    delete_branch_after_merge: bool = True

    def is_protected(self, branch: str) -> bool:
        """Check if a branch requires user approval to merge to."""
        return branch in self.protected_branches

    def can_auto_merge(self, target_branch: str) -> bool:
        """Check if auto-merge is allowed for this target."""
        if self.is_protected(target_branch):
            return False
        if target_branch == self.staging_branch:
            return True
        return self.auto_merge_on_tests_pass
