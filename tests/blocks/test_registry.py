"""Tests for the block registry."""

from pathlib import Path

import pytest

from guild.blocks import (
    BlockDef,
    BlockRegistry,
    Connection,
    LoopDef,
    PortDef,
    TeamDef,
)


@pytest.mark.unit
@pytest.mark.req("REQ-04.23")
def test_registry_has_builtin_blocks() -> None:
    """Registry should contain 6 built-in blocks on creation."""
    registry = BlockRegistry()
    blocks = registry.list_blocks()
    assert len(blocks) >= 6
    # Verify a few specific blocks
    planner = registry.get_block("planner")
    assert planner is not None
    assert planner.role == "planner"
    coder = registry.get_block("coder")
    assert coder is not None
    assert coder.permission == "scoped"


@pytest.mark.unit
@pytest.mark.req("REQ-04.23")
def test_register_custom_block() -> None:
    """Users can register custom blocks."""
    registry = BlockRegistry()
    custom = BlockDef(
        name="summarizer",
        role="summarizer",
        inputs=[PortDef(name="document", type_tag="text")],
        outputs=[PortDef(name="summary", type_tag="text")],
    )
    registry.register_block(custom)
    assert registry.get_block("summarizer") is not None
    assert registry.get_block("summarizer") == custom


@pytest.mark.unit
@pytest.mark.req("REQ-04.23")
def test_load_blocks_from_toml_directory(tmp_path: object) -> None:
    """Registry can load block definitions from a directory of TOML files."""
    from pathlib import Path

    blocks_dir = Path(str(tmp_path)) / "blocks"
    blocks_dir.mkdir()

    toml_content = """\
[block]
name = "doc-writer"
role = "writer"
version = "2.0.0"
system_prompt = "Write documentation."
tools = ["file_write"]
permission = "scoped"

[[block.inputs]]
name = "source"
type = "code-changes"

[[block.outputs]]
name = "docs"
type = "text"
"""
    (blocks_dir / "doc_writer.toml").write_text(toml_content)

    registry = BlockRegistry()
    count = registry.load_from_dir(blocks_dir)
    assert count == 1

    loaded = registry.get_block("doc-writer")
    assert loaded is not None
    assert loaded.version == "2.0.0"
    assert loaded.role == "writer"
    assert loaded.inputs[0].type_tag == "code-changes"
    assert loaded.outputs[0].type_tag == "text"
    assert loaded.permission == "scoped"


@pytest.mark.unit
@pytest.mark.req("REQ-04.21")
def test_team_composition_validates() -> None:
    """A valid team composition passes validation."""
    registry = BlockRegistry()
    team = TeamDef(
        name="dev-team",
        blocks={
            "plan": "planner",
            "code": "coder",
            "review": "reviewer",
        },
        connections=[
            Connection(
                source_block="plan",
                source_port="plan",
                target_block="code",
                target_port="spec",
            ),
            Connection(
                source_block="code",
                source_port="changes",
                target_block="review",
                target_port="changes",
            ),
        ],
        entry_block="plan",
    )
    errors = registry.validate_team(team)
    assert errors == []


@pytest.mark.unit
@pytest.mark.req("REQ-04.21")
def test_team_with_incompatible_ports_fails() -> None:
    """A team with type-mismatched ports fails validation."""
    registry = BlockRegistry()
    team = TeamDef(
        name="bad-team",
        blocks={
            "plan": "planner",
            "test": "tester",
        },
        connections=[
            Connection(
                source_block="plan",
                source_port="plan",
                target_block="test",
                target_port="changes",  # expects code-changes, gets plan
            ),
        ],
        entry_block="plan",
    )
    errors = registry.validate_team(team)
    assert len(errors) > 0
    assert any("mismatch" in e.lower() or "type" in e.lower() for e in errors)


@pytest.mark.unit
@pytest.mark.req("REQ-04.24")
def test_team_from_toml_file(tmp_path: object) -> None:
    """Teams can be loaded from TOML config files."""
    from pathlib import Path

    blocks_dir = Path(str(tmp_path)) / "blocks"
    blocks_dir.mkdir()

    toml_content = """\
[team]
name = "review-loop"
description = "A code-review team"
version = "1.2.0"
entry_block = "code"

[team.blocks]
code = "coder"
review = "reviewer"

[[team.connections]]
source_block = "code"
source_port = "changes"
target_block = "review"
target_port = "changes"
"""
    (blocks_dir / "review_team.toml").write_text(toml_content)

    registry = BlockRegistry()
    count = registry.load_from_dir(blocks_dir)
    assert count == 1

    team = registry.get_team("review-loop")
    assert team is not None
    assert team.version == "1.2.0"
    assert team.entry_block == "code"
    assert len(team.connections) == 1
    assert team.blocks["code"] == "coder"


@pytest.mark.unit
@pytest.mark.req("REQ-04.25")
def test_nested_composite_blocks() -> None:
    """Composite blocks can reference other composite blocks (nesting)."""
    registry = BlockRegistry()

    # Register an inner team as a block (composite block pattern)
    inner_team = TeamDef(
        name="inner-review",
        blocks={"code": "coder", "review": "reviewer"},
        connections=[
            Connection(
                source_block="code",
                source_port="changes",
                target_block="review",
                target_port="changes",
            ),
        ],
        entry_block="code",
    )
    registry.register_team(inner_team)

    # Register a composite block wrapper that references the inner team
    composite_block = BlockDef(
        name="inner-review",
        role="composite",
        inputs=[PortDef(name="spec", type_tag="plan")],
        outputs=[PortDef(name="result", type_tag="review")],
    )
    registry.register_block(composite_block)

    # Use it in an outer team
    outer_team = TeamDef(
        name="outer-pipeline",
        blocks={
            "plan": "planner",
            "dev": "inner-review",
        },
        connections=[
            Connection(
                source_block="plan",
                source_port="plan",
                target_block="dev",
                target_port="spec",
            ),
        ],
        entry_block="plan",
    )
    errors = registry.validate_team(outer_team)
    assert errors == []
    # Verify the inner team is also retrievable
    assert registry.get_team("inner-review") is not None


@pytest.mark.unit
@pytest.mark.req("REQ-14.2")
def test_team_composition_loaded_as_named_config(tmp_path: object) -> None:
    """Team compositions are loadable as named configs from TOML (REQ-14.2)."""
    from pathlib import Path

    blocks_dir = Path(str(tmp_path)) / "teams"
    blocks_dir.mkdir()

    # Write two named team configurations
    team_toml_1 = """\
[team]
name = "fast-review"
description = "Quick code review pipeline"
version = "1.0.0"
entry_block = "code"

[team.blocks]
code = "coder"
review = "reviewer"

[[team.connections]]
source_block = "code"
source_port = "changes"
target_block = "review"
target_port = "changes"
"""
    team_toml_2 = """\
[team]
name = "full-pipeline"
description = "Plan, code, test, review"
version = "2.0.0"
entry_block = "plan"

[team.blocks]
plan = "planner"
code = "coder"
test = "tester"

[[team.connections]]
source_block = "plan"
source_port = "plan"
target_block = "code"
target_port = "spec"

[[team.connections]]
source_block = "code"
source_port = "changes"
target_block = "test"
target_port = "changes"
"""
    (blocks_dir / "fast_review.toml").write_text(team_toml_1)
    (blocks_dir / "full_pipeline.toml").write_text(team_toml_2)

    registry = BlockRegistry()
    count = registry.load_from_dir(blocks_dir)
    assert count == 2

    # Both teams are accessible by name
    fast = registry.get_team("fast-review")
    assert fast is not None
    assert fast.description == "Quick code review pipeline"

    full = registry.get_team("full-pipeline")
    assert full is not None
    assert full.version == "2.0.0"
    assert full.entry_block == "plan"
    assert len(full.connections) == 2


@pytest.mark.unit
@pytest.mark.req("REQ-04.26")
def test_block_versioning() -> None:
    """Blocks carry version info that can be compared."""
    registry = BlockRegistry()
    planner = registry.get_block("planner")
    assert planner is not None
    assert planner.version == "1.0.0"

    # Register an updated version
    updated = BlockDef(
        name="planner",
        role="planner",
        version="2.0.0",
        inputs=[PortDef(name="task", type_tag="text")],
        outputs=[PortDef(name="plan", type_tag="plan")],
    )
    registry.register_block(updated)
    assert registry.get_block("planner") is not None
    assert registry.get_block("planner").version == "2.0.0"  # type: ignore[union-attr]


@pytest.mark.unit
@pytest.mark.req("REQ-04.27")
def test_loop_definition_valid() -> None:
    """Loop definitions specify generator and evaluator blocks."""
    loop = LoopDef(
        generator_block="coder",
        evaluator_block="reviewer",
        max_iterations=3,
    )
    assert loop.generator_block == "coder"
    assert loop.evaluator_block == "reviewer"
    assert loop.max_iterations == 3


@pytest.mark.unit
@pytest.mark.req("REQ-04.27")
def test_validate_team_with_loops() -> None:
    """Teams with valid loops pass validation."""
    registry = BlockRegistry()
    team = TeamDef(
        name="loop-team",
        blocks={
            "code": "coder",
            "eval": "evaluator",
        },
        connections=[
            Connection(
                source_block="code",
                source_port="changes",
                target_block="eval",
                target_port="artifact",
            ),
        ],
        loops=[
            LoopDef(
                generator_block="code",
                evaluator_block="eval",
                max_iterations=5,
            ),
        ],
        entry_block="code",
    )
    errors = registry.validate_team(team)
    assert errors == []

    # Invalid loop — reference to non-existent block
    bad_team = TeamDef(
        name="bad-loop-team",
        blocks={"code": "coder"},
        connections=[],
        loops=[
            LoopDef(
                generator_block="code",
                evaluator_block="missing",
                max_iterations=3,
            ),
        ],
        entry_block="code",
    )
    errors = registry.validate_team(bad_team)
    assert len(errors) > 0
    assert any("missing" in e for e in errors)


# ======================================================================
# Block Registry validation edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.21")
class TestRegistryValidationEdgeCases:
    """Cover remaining validation edge cases in BlockRegistry."""

    def test_empty_entry_block_error(self) -> None:
        """Team with empty entry_block produces validation error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="no-entry",
            blocks={"code": "coder"},
            connections=[],
            entry_block="",
        )
        errors = registry.validate_team(team)
        assert any("entry_block" in e.lower() for e in errors)

    def test_entry_block_not_in_team_error(self) -> None:
        """Team with entry_block not in blocks dict produces validation error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-entry",
            blocks={"code": "coder"},
            connections=[],
            entry_block="missing",
        )
        errors = registry.validate_team(team)
        assert any("missing" in e and "not in team" in e for e in errors)

    def test_unregistered_block_type_error(self) -> None:
        """Team referencing an unknown block type produces validation error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="unknown-type",
            blocks={"x": "nonexistent_block_type"},
            connections=[],
            entry_block="x",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_block_type" in e and "not found" in e for e in errors)

    def test_connection_source_not_in_team(self) -> None:
        """Connection referencing a source block not in team produces error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-conn-src",
            blocks={"code": "coder"},
            connections=[
                Connection(
                    source_block="ghost",
                    source_port="plan",
                    target_block="code",
                    target_port="spec",
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("ghost" in e and "source" in e.lower() for e in errors)

    def test_connection_target_not_in_team(self) -> None:
        """Connection referencing a target block not in team produces error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-conn-tgt",
            blocks={"plan": "planner"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="plan",
                    target_block="ghost",
                    target_port="spec",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("ghost" in e and "target" in e.lower() for e in errors)

    def test_connection_with_unregistered_block_types(self) -> None:
        """Connection where block type not in registry returns early."""
        registry = BlockRegistry()
        team = TeamDef(
            name="unregistered-types",
            blocks={"a": "fake_type_a", "b": "fake_type_b"},
            connections=[
                Connection(
                    source_block="a",
                    source_port="out",
                    target_block="b",
                    target_port="in",
                ),
            ],
            entry_block="a",
        )
        errors = registry.validate_team(team)
        # Should get "not found in registry" errors for both blocks
        assert any("fake_type_a" in e for e in errors)

    def test_invalid_output_port_name_error(self) -> None:
        """Connection referencing nonexistent output port produces error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-port",
            blocks={"plan": "planner", "code": "coder"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="nonexistent_output",
                    target_block="code",
                    target_port="spec",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_output" in e and "not found" in e for e in errors)

    def test_invalid_input_port_name_error(self) -> None:
        """Connection referencing nonexistent input port produces error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-input-port",
            blocks={"plan": "planner", "code": "coder"},
            connections=[
                Connection(
                    source_block="plan",
                    source_port="plan",
                    target_block="code",
                    target_port="nonexistent_input",
                ),
            ],
            entry_block="plan",
        )
        errors = registry.validate_team(team)
        assert any("nonexistent_input" in e and "not found" in e for e in errors)

    def test_load_from_nonexistent_dir_returns_zero(self) -> None:
        """Loading from a non-directory path returns 0."""
        registry = BlockRegistry()
        count = registry.load_from_dir(Path("/nonexistent/path"))
        assert count == 0

    def test_load_from_dir_bad_toml_logs_error(self, tmp_path: Path) -> None:
        """Invalid TOML file is gracefully skipped."""
        blocks_dir = tmp_path / "blocks"
        blocks_dir.mkdir()
        (blocks_dir / "bad.toml").write_text("this is [not valid toml")

        registry = BlockRegistry()
        count = registry.load_from_dir(blocks_dir)
        assert count == 0

    def test_list_teams_returns_registered_teams(self) -> None:
        """list_teams returns all registered team definitions."""
        registry = BlockRegistry()
        team = TeamDef(
            name="test-team",
            blocks={"code": "coder"},
            connections=[],
            entry_block="code",
        )
        registry.register_team(team)
        teams = registry.list_teams()
        assert len(teams) >= 1
        assert any(t.name == "test-team" for t in teams)

    def test_loop_max_iterations_less_than_1_error(self) -> None:
        """Loop with max_iterations < 1 produces validation error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="bad-loop-iters",
            blocks={"code": "coder", "eval": "evaluator"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="code",
                    evaluator_block="eval",
                    max_iterations=0,
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("max_iterations" in e for e in errors)

    def test_loop_evaluator_not_in_team(self) -> None:
        """Loop referencing non-existent evaluator produces error."""
        registry = BlockRegistry()
        team = TeamDef(
            name="loop-no-eval",
            blocks={"code": "coder"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="code",
                    evaluator_block="ghost_evaluator",
                    max_iterations=3,
                ),
            ],
            entry_block="code",
        )
        errors = registry.validate_team(team)
        assert any("ghost_evaluator" in e for e in errors)


# ======================================================================
# Block registry loop validation (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.27")
class TestRegistryLoopValidation:
    """Validate loop blocks must be in the team."""

    def test_loop_generator_not_in_team(self) -> None:
        """Loop with generator not in team.blocks errors."""
        registry = BlockRegistry()
        team = TeamDef(
            name="loop-gen-missing",
            blocks={"eval": "evaluator"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="ghost_gen",
                    evaluator_block="eval",
                    max_iterations=3,
                ),
            ],
            entry_block="eval",
        )
        errors = registry.validate_team(team)
        assert any("ghost_gen" in e for e in errors)
