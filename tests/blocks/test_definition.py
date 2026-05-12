"""Tests for block definitions and port types."""

import pytest

from guild.blocks import BlockDef, PortDef
from guild.blocks.port_types import check_port_compatibility
from guild.blocks.registry import BlockRegistry


@pytest.mark.unit
def test_atomic_block_has_inputs_outputs() -> None:
    """An atomic block must define typed input and output ports."""
    block = BlockDef(
        name="my-block",
        role="worker",
        inputs=[PortDef(name="task", type_tag="text")],
        outputs=[PortDef(name="result", type_tag="text")],
    )
    assert len(block.inputs) == 1
    assert len(block.outputs) == 1
    assert block.inputs[0].name == "task"
    assert block.inputs[0].type_tag == "text"
    assert block.outputs[0].name == "result"
    assert block.outputs[0].type_tag == "text"


@pytest.mark.unit
def test_builtin_blocks_registered() -> None:
    """All built-in blocks should be registered on init."""
    registry = BlockRegistry()
    blocks = registry.list_blocks()
    names = {b.name for b in blocks}
    expected = {"planner", "coder", "reviewer", "tester", "evaluator", "researcher"}
    assert expected.issubset(names)


@pytest.mark.unit
def test_block_has_all_required_fields() -> None:
    """A BlockDef has name, role, and all structural fields accessible."""
    block = BlockDef(
        name="coder",
        role="developer",
        version="2.0.0",
        system_prompt="You write code.",
        model="llama3",
        tools=["file_read", "file_write", "shell"],
        inputs=[PortDef(name="plan", type_tag="plan")],
        outputs=[PortDef(name="code", type_tag="code-changes")],
        permission="scoped",
        max_retries=3,
    )
    assert block.name == "coder"
    assert block.role == "developer"
    assert block.version == "2.0.0"
    assert block.system_prompt == "You write code."
    assert block.model == "llama3"
    assert block.tools == ["file_read", "file_write", "shell"]
    assert block.permission == "scoped"
    assert block.max_retries == 3
    assert len(block.inputs) == 1
    assert len(block.outputs) == 1


@pytest.mark.unit
def test_block_default_permission() -> None:
    """A BlockDef without explicit permission defaults to 'ask'."""
    block = BlockDef(name="minimal", role="worker")
    assert block.permission == "ask"
    assert block.model is None
    assert block.tools == []
    assert block.inputs == []
    assert block.outputs == []
    assert block.max_retries == 1
    assert block.version == "1.0.0"


@pytest.mark.unit
def test_port_compatibility_same_type() -> None:
    """Ports with the same type tag are compatible."""
    assert check_port_compatibility("plan", "plan") is True
    assert check_port_compatibility("code-changes", "code-changes") is True
    assert check_port_compatibility("text", "text") is True


@pytest.mark.unit
def test_port_compatibility_any_accepts_all() -> None:
    """The 'any' type is compatible with all other types."""
    assert check_port_compatibility("any", "plan") is True
    assert check_port_compatibility("code-changes", "any") is True
    assert check_port_compatibility("any", "any") is True


@pytest.mark.unit
def test_port_compatibility_mismatch_rejects() -> None:
    """Ports with different non-any types are incompatible."""
    assert check_port_compatibility("plan", "code-changes") is False
    assert check_port_compatibility("text", "review") is False
    assert check_port_compatibility("files", "test-results") is False


@pytest.mark.unit
def test_incompatible_ports_detected() -> None:
    """Incompatible port types are explicitly detected as False."""
    # All combinations of non-matching, non-any types
    assert check_port_compatibility("plan", "text") is False
    assert check_port_compatibility("code-changes", "review") is False
    assert check_port_compatibility("test-results", "plan") is False
    assert check_port_compatibility("files", "code-changes") is False
    # Symmetric: order should not matter for incompatibility
    assert check_port_compatibility("review", "plan") is False
    assert check_port_compatibility("plan", "review") is False


@pytest.mark.unit
def test_any_connects_to_anything() -> None:
    """'any' type is compatible with all known port types in both directions."""
    port_types = ["plan", "code-changes", "review", "test-results", "text", "files", "any"]
    for pt in port_types:
        assert check_port_compatibility("any", pt) is True
        assert check_port_compatibility(pt, "any") is True
