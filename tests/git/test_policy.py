"""Tests for guild.git.policy — branch policy configuration."""

import pytest

from guild.git.policy import BranchPolicy, MergeApproval


@pytest.mark.unit
@pytest.mark.req("REQ-04.13")
class TestProtectedBranches:
    """Test that protected branches block auto-merge."""

    def test_main_is_protected_by_default(self) -> None:
        policy = BranchPolicy()
        assert policy.is_protected("main")
        assert policy.is_protected("master")

    def test_protected_branch_blocks_auto_merge(self) -> None:
        policy = BranchPolicy()
        assert not policy.can_auto_merge("main")
        assert not policy.can_auto_merge("master")

    def test_staging_allows_auto_merge(self) -> None:
        policy = BranchPolicy()
        assert policy.can_auto_merge("guild/staging")


@pytest.mark.unit
@pytest.mark.req("REQ-04.15")
class TestPolicyConfigurable:
    """Test that merge policy is configurable per project."""

    def test_policy_configurable(self) -> None:
        policy = BranchPolicy(
            protected_branches=["main", "release"],
            staging_branch="dev/staging",
            merge_approval=MergeApproval.AUTO,
            auto_merge_on_tests_pass=True,
            delete_branch_after_merge=False,
        )
        assert policy.is_protected("release")
        assert not policy.is_protected("master")
        assert policy.staging_branch == "dev/staging"
        assert policy.merge_approval == MergeApproval.AUTO
        assert policy.auto_merge_on_tests_pass is True
        assert policy.delete_branch_after_merge is False

    def test_can_auto_merge_with_tests_pass_flag(self) -> None:
        policy = BranchPolicy(auto_merge_on_tests_pass=True)
        # Random feature branch should auto-merge when tests pass
        assert policy.can_auto_merge("feature/foo")
        # Protected branches still block
        assert not policy.can_auto_merge("main")

    def test_auto_merge_disabled_by_default_for_random_branches(self) -> None:
        policy = BranchPolicy()
        # Without auto_merge_on_tests_pass, random branches don't auto-merge
        assert not policy.can_auto_merge("feature/foo")

    def test_custom_staging_branch_allows_auto_merge(self) -> None:
        policy = BranchPolicy(staging_branch="integration")
        assert policy.can_auto_merge("integration")
        # Default staging name no longer auto-merges
        assert not policy.can_auto_merge("guild/staging")
