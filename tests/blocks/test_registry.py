"""Tests for the block registry."""

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
