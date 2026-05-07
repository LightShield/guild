"""Tests for block definitions and port types."""

import pytest

from guild.blocks import BlockDef, PortDef
from guild.blocks.port_types import check_port_compatibility
from guild.blocks.registry import BlockRegistry


@pytest.mark.unit
@pytest.mark.req("REQ-04.20")
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
@pytest.mark.req("REQ-04.20")
def test_builtin_blocks_registered() -> None:
    """All built-in blocks should be registered on init."""
    registry = BlockRegistry()
    blocks = registry.list_blocks()
    names = {b.name for b in blocks}
    expected = {"planner", "coder", "reviewer", "tester", "evaluator", "researcher"}
    assert expected.issubset(names)


@pytest.mark.unit
@pytest.mark.req("REQ-04.22")
def test_port_compatibility_same_type() -> None:
    """Ports with the same type tag are compatible."""
    assert check_port_compatibility("plan", "plan") is True
    assert check_port_compatibility("code-changes", "code-changes") is True
    assert check_port_compatibility("text", "text") is True


@pytest.mark.unit
@pytest.mark.req("REQ-04.22")
def test_port_compatibility_any_accepts_all() -> None:
    """The 'any' type is compatible with all other types."""
    assert check_port_compatibility("any", "plan") is True
    assert check_port_compatibility("code-changes", "any") is True
    assert check_port_compatibility("any", "any") is True


@pytest.mark.unit
@pytest.mark.req("REQ-04.22")
def test_port_compatibility_mismatch_rejects() -> None:
    """Ports with different non-any types are incompatible."""
    assert check_port_compatibility("plan", "code-changes") is False
    assert check_port_compatibility("text", "review") is False
    assert check_port_compatibility("files", "test-results") is False
