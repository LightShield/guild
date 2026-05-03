"""Tests for blocks/registry.py — built-in blocks, team validation, port type checking, TOML loading."""

import pytest

pytestmark = pytest.mark.unit
from pathlib import Path

from guild.blocks.registry import (
    BUILTIN_BLOCKS, BUILTIN_TEAMS, BlockRegistry,
    Connection, LoopDef, TeamDef,
)
from guild.core.models import BlockDef, PortDef, PermissionTier


class TestBuiltinBlocks:
    def test_all_expected_blocks_exist(self):
        expected = {"planner", "coder", "reviewer", "tester", "evaluator", "researcher", "writer", "learner"}
        assert set(BUILTIN_BLOCKS.keys()) == expected

    def test_all_blocks_have_system_prompt(self):
        for name, block in BUILTIN_BLOCKS.items():
            assert block.system_prompt, f"Block '{name}' has empty system prompt"

    def test_all_blocks_have_ports(self):
        for name, block in BUILTIN_BLOCKS.items():
            assert block.inputs, f"Block '{name}' has no inputs"
            assert block.outputs, f"Block '{name}' has no outputs"

    def test_coder_has_write_tools(self):
        coder = BUILTIN_BLOCKS["coder"]
        assert "file_write" in coder.tools
        assert "file_read" in coder.tools

    def test_evaluator_accepts_any_input(self):
        ev = BUILTIN_BLOCKS["evaluator"]
        artifact_port = next(p for p in ev.inputs if p.name == "artifact")
        assert artifact_port.type_tag == "any"


class TestBuiltinTeams:
    def test_all_expected_teams_exist(self):
        expected = {"dev-loop", "verified-coder", "research-and-implement"}
        assert set(BUILTIN_TEAMS.keys()) == expected

    def test_dev_loop_has_all_blocks(self):
        team = BUILTIN_TEAMS["dev-loop"]
        assert set(team.blocks.keys()) == {"planner", "coder", "tester", "reviewer"}

    def test_dev_loop_has_loop(self):
        team = BUILTIN_TEAMS["dev-loop"]
        assert len(team.loops) == 1
        assert team.loops[0].evaluator_block == "reviewer"
        assert team.loops[0].generator_block == "coder"

    def test_verified_coder_loop(self):
        team = BUILTIN_TEAMS["verified-coder"]
        assert team.loops[0].max_iterations == 5


class TestBlockRegistry:
    def test_loads_builtins(self):
        r = BlockRegistry()
        assert "coder" in r.blocks
        assert "dev-loop" in r.teams

    def test_get_block(self):
        r = BlockRegistry()
        assert r.get_block("coder") is not None
        assert r.get_block("nonexistent") is None

    def test_get_team(self):
        r = BlockRegistry()
        assert r.get_team("dev-loop") is not None
        assert r.get_team("nonexistent") is None


class TestTeamValidation:
    def test_valid_team(self):
        r = BlockRegistry()
        errors = r.validate_team(BUILTIN_TEAMS["dev-loop"])
        assert errors == []

    def test_missing_block_type(self):
        r = BlockRegistry()
        team = TeamDef(
            name="bad", blocks={"x": "nonexistent_block"},
            connections=[], entry_block="x",
        )
        errors = r.validate_team(team)
        assert any("not found" in e for e in errors)

    def test_missing_connection_source(self):
        r = BlockRegistry()
        team = TeamDef(
            name="bad", blocks={"coder": "coder"},
            connections=[Connection(source_block="ghost", source_port="p", target_block="coder", target_port="spec")],
        )
        errors = r.validate_team(team)
        assert any("ghost" in e for e in errors)

    def test_port_type_mismatch(self):
        r = BlockRegistry()
        # reviewer outputs review, but planner expects text input
        team = TeamDef(
            name="bad",
            blocks={"reviewer": "reviewer", "planner": "planner"},
            connections=[Connection(
                source_block="reviewer", source_port="result",
                target_block="planner", target_port="task",
            )],
        )
        errors = r.validate_team(team)
        assert any("type mismatch" in e.lower() for e in errors)

    def test_any_type_is_compatible(self):
        r = BlockRegistry()
        # evaluator accepts 'any' input — should be compatible with anything
        team = TeamDef(
            name="ok",
            blocks={"coder": "coder", "evaluator": "evaluator"},
            connections=[Connection(
                source_block="coder", source_port="changes",
                target_block="evaluator", target_port="artifact",
            )],
        )
        errors = r.validate_team(team)
        assert errors == []

    def test_invalid_entry_block(self):
        r = BlockRegistry()
        team = TeamDef(
            name="bad", blocks={"coder": "coder"},
            connections=[], entry_block="nonexistent",
        )
        errors = r.validate_team(team)
        assert any("entry" in e.lower() for e in errors)


class TestTomlLoading:
    def test_load_custom_block(self, tmp_path):
        block_toml = tmp_path / "custom.toml"
        block_toml.write_text("""
[block]
name = "my-block"
role = "custom"
system_prompt = "You are custom."
tools = ["file_read"]
permission = "scoped"

[[block.inputs]]
name = "data"
type_tag = "text"

[[block.outputs]]
name = "result"
type_tag = "text"
""")
        r = BlockRegistry()
        r.load_from_dir(tmp_path)
        block = r.get_block("my-block")
        assert block is not None
        assert block.role == "custom"
        assert block.permission == PermissionTier.SCOPED
        assert len(block.inputs) == 1
        assert block.inputs[0].type_tag == "text"

    def test_load_custom_team(self, tmp_path):
        team_toml = tmp_path / "my-team.toml"
        team_toml.write_text("""
[team]
name = "my-team"
description = "Custom team"
entry_block = "coder"

[team.blocks]
coder = "coder"
reviewer = "reviewer"

[[team.connections]]
source_block = "coder"
source_port = "changes"
target_block = "reviewer"
target_port = "changes"
""")
        r = BlockRegistry()
        r.load_from_dir(tmp_path)
        team = r.get_team("my-team")
        assert team is not None
        assert team.description == "Custom team"
        assert len(team.connections) == 1

    def test_bad_toml_skipped(self, tmp_path):
        (tmp_path / "bad.toml").write_text("this is not valid toml {{{}}")
        r = BlockRegistry()
        r.load_from_dir(tmp_path)  # should not raise
        # Built-ins still present
        assert "coder" in r.blocks

    def test_load_from_nonexistent_dir(self):
        r = BlockRegistry()
        r.load_from_dir(Path("/nonexistent/dir"))  # should not raise
        assert "coder" in r.blocks
