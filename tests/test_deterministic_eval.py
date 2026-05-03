"""Tests for deterministic evaluator checks (D-05 fix)."""

import pytest
from unittest.mock import AsyncMock

pytestmark = pytest.mark.unit

from guild.blocks.registry import BlockRegistry, LoopDef, TeamDef, Connection
from guild.core.models import PermissionTier
from guild.core.storage import Storage
from guild.core.team_runner import TeamRunner
from guild.providers.base import LLMResponse


@pytest.fixture
async def storage(tmp_path):
    s = Storage(tmp_path / "test.db")
    await s.connect()
    yield s
    await s.close()


def make_provider(responses: list[str]) -> AsyncMock:
    provider = AsyncMock()
    resps = [LLMResponse(content=r, input_tokens=10, output_tokens=5) for r in responses]
    provider.generate = AsyncMock(side_effect=resps)
    provider.health_check = AsyncMock(return_value=True)
    return provider


class TestDeterministicVerification:
    """D-05: Evaluator pass/fail via deterministic checks, not LLM text parsing."""

    async def test_verification_command_pass(self, storage, tmp_path):
        """Shell command exit 0 = pass, regardless of LLM output."""
        team = TeamDef(
            name="test",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
            loops=[LoopDef(
                evaluator_block="evaluator",
                generator_block="coder",
                max_iterations=3,
                verification_commands=["true"],  # always exits 0
            )],
            entry_block="coder",
        )
        registry = BlockRegistry()
        # LLM says "fail" but deterministic check says pass
        provider = make_provider(["code v1", "This is terrible, fail!"])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir=str(tmp_path),
            permission_tier=PermissionTier.AUTOPILOT,
        )
        result = await runner.run("write code")
        # Should have exited after 1 iteration (deterministic pass overrides LLM)
        assert provider.generate.call_count == 2

    async def test_verification_command_fail_triggers_retry(self, storage, tmp_path):
        """Shell command exit non-0 = fail, triggers retry."""
        team = TeamDef(
            name="test",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
            loops=[LoopDef(
                evaluator_block="evaluator",
                generator_block="coder",
                max_iterations=2,
                verification_commands=["false"],  # always exits 1
            )],
            entry_block="coder",
        )
        registry = BlockRegistry()
        # LLM says "pass" but deterministic check says fail
        provider = make_provider([
            "code v1", '{"pass": true}',
            "code v2", '{"pass": true}',
        ])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir=str(tmp_path),
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("write code")
        # Should have retried (deterministic fail overrides LLM pass)
        assert provider.generate.call_count == 4

    async def test_verification_file_check(self, storage, tmp_path):
        """File existence check as deterministic verification."""
        # Create the expected file
        (tmp_path / "output.txt").write_text("result")

        team = TeamDef(
            name="test",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
            loops=[LoopDef(
                evaluator_block="evaluator",
                generator_block="coder",
                max_iterations=3,
                verification_files=[str(tmp_path / "output.txt")],
            )],
            entry_block="coder",
        )
        registry = BlockRegistry()
        provider = make_provider(["code", "whatever"])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir=str(tmp_path),
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("task")
        assert provider.generate.call_count == 2  # No retry needed

    async def test_missing_file_triggers_retry(self, storage, tmp_path):
        """Missing verification file = fail."""
        team = TeamDef(
            name="test",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
            loops=[LoopDef(
                evaluator_block="evaluator",
                generator_block="coder",
                max_iterations=2,
                verification_files=[str(tmp_path / "nonexistent.txt")],
            )],
            entry_block="coder",
        )
        registry = BlockRegistry()
        provider = make_provider(["code v1", "looks good", "code v2", "looks good"])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir=str(tmp_path),
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("task")
        assert provider.generate.call_count == 4  # Retried

    async def test_no_deterministic_checks_falls_back_to_llm(self, storage, tmp_path):
        """Without verification_commands/files, falls back to LLM text parsing."""
        team = TeamDef(
            name="test",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
            loops=[LoopDef(
                evaluator_block="evaluator",
                generator_block="coder",
                max_iterations=3,
                # No verification_commands or verification_files
            )],
            entry_block="coder",
        )
        registry = BlockRegistry()
        provider = make_provider(["code", '{"pass": true, "score": 90}'])
        runner = TeamRunner(
            team, registry, provider, storage,
            working_dir=str(tmp_path),
            permission_tier=PermissionTier.AUTOPILOT,
        )
        await runner.run("task")
        assert provider.generate.call_count == 2  # LLM said pass
