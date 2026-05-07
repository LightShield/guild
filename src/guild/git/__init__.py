"""Git worktree isolation and branching strategy for Guild."""

from guild.git.policy import BranchPolicy, MergeApproval
from guild.git.worktree import WorktreeInfo, WorktreeManager

__all__ = [
    "BranchPolicy",
    "MergeApproval",
    "WorktreeInfo",
    "WorktreeManager",
]
