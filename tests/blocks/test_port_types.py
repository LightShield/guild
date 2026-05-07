"""Tests for enhanced port type system (REQ-04.30 through REQ-04.35)."""

from __future__ import annotations

import pytest

from guild.blocks.definition import Connection, TeamDef
from guild.blocks.port_types import (
    PORT_TYPE_REGISTRY,
    check_port_compatibility,
    get_composite_ports,
    register_port_type,
    validate_port_data,
)
from guild.blocks.registry import BlockRegistry


@pytest.mark.unit
@pytest.mark.req("REQ-04.30")
def test_port_type_has_tag_and_schema() -> None:
    """Every port type can have a type tag and optional JSON schema."""
    register_port_type(
        "structured-plan",
        json_schema={
            "type": "object",
            "properties": {"steps": {"type": "array"}},
            "required": ["steps"],
        },
        description="A structured plan with steps",
    )
    entry = PORT_TYPE_REGISTRY["structured-plan"]
    assert entry.type_tag == "structured-plan"
    assert entry.json_schema is not None
    assert entry.json_schema["type"] == "object"
    assert entry.description == "A structured plan with steps"


@pytest.mark.unit
@pytest.mark.req("REQ-04.31")
def test_compatibility_checked_at_composition() -> None:
    """Port compatibility is checked at composition time (validate_team)."""
    registry = BlockRegistry()
    team = TeamDef(
        name="mismatch-team",
        blocks={"plan": "planner", "test": "tester"},
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
@pytest.mark.req("REQ-04.32")
def test_any_type_accepts_all() -> None:
    """The 'any' type tag is compatible with every other type."""
    assert check_port_compatibility("any", "plan") is True
    assert check_port_compatibility("code-changes", "any") is True
    assert check_port_compatibility("any", "any") is True
    assert check_port_compatibility("text", "review") is False


@pytest.mark.unit
@pytest.mark.req("REQ-04.33")
def test_composite_exposes_unconnected_ports() -> None:
    """Composite blocks expose unconnected inner ports as their own ports."""
    registry = BlockRegistry()
    team = TeamDef(
        name="composite-team",
        blocks={
            "plan": "planner",
            "code": "coder",
        },
        connections=[
            Connection(
                source_block="plan",
                source_port="plan",
                target_block="code",
                target_port="spec",
            ),
        ],
        entry_block="plan",
    )
    exposed_inputs, exposed_outputs = get_composite_ports(team, registry)

    # Planner has input "task" (text) - not connected, so exposed
    input_names = [p.name for p in exposed_inputs]
    assert "task" in input_names

    # Coder has input "context" (files) - not connected, so exposed
    assert "context" in input_names

    # Planner's "plan" output is connected, so NOT exposed
    output_names = [p.name for p in exposed_outputs]
    assert "plan" not in output_names

    # Coder has output "changes" (code-changes) - not connected, so exposed
    assert "changes" in output_names


@pytest.mark.unit
@pytest.mark.req("REQ-04.34")
def test_register_custom_port_type() -> None:
    """New type tags can be registered by users."""
    register_port_type(
        "metrics",
        json_schema={"type": "object", "properties": {"score": {"type": "number"}}},
        description="Performance metrics",
    )
    assert "metrics" in PORT_TYPE_REGISTRY
    entry = PORT_TYPE_REGISTRY["metrics"]
    assert entry.type_tag == "metrics"
    assert entry.description == "Performance metrics"


@pytest.mark.unit
@pytest.mark.req("REQ-04.35")
def test_port_data_must_be_json_serializable() -> None:
    """Port data must always be JSON-serializable."""
    valid, error = validate_port_data({"key": "value", "count": 42}, "text")
    assert valid is True
    assert error == ""


@pytest.mark.unit
@pytest.mark.req("REQ-04.35")
def test_non_serializable_data_rejected() -> None:
    """Non-JSON-serializable data is rejected."""
    valid, error = validate_port_data({"func": lambda x: x}, "text")  # type: ignore[dict-item]
    assert valid is False
    assert "not JSON-serializable" in error
