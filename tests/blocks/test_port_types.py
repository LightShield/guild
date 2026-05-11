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


# ------------------------------------------------------------------
# Schema validation tests (basic_schema_check + validate_port_data)
# ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-04.35")
class TestBasicSchemaCheck:
    """Tests for _basic_schema_check and validate_port_data with schemas."""

    def test_object_type_check_passes_with_dict(self) -> None:
        """Object schema type passes when data is a dict."""
        register_port_type(
            "object-type-test",
            json_schema={"type": "object", "properties": {}},
        )
        valid, error = validate_port_data({"key": "value"}, "object-type-test")
        assert valid is True
        assert error == ""

    def test_object_type_check_fails_with_list(self) -> None:
        """Object schema type fails when data is a list."""
        register_port_type(
            "object-only",
            json_schema={"type": "object", "properties": {}},
        )
        valid, error = validate_port_data([1, 2, 3], "object-only")  # type: ignore[arg-type]
        assert valid is False
        assert "does not match schema" in error

    def test_array_type_check_passes_with_list(self) -> None:
        """Array schema type passes when data is a list."""
        register_port_type(
            "array-type-test",
            json_schema={"type": "array", "items": {"type": "string"}},
        )
        valid, error = validate_port_data(["a", "b"], "array-type-test")  # type: ignore[arg-type]
        assert valid is True
        assert error == ""

    def test_array_type_check_fails_with_dict(self) -> None:
        """Array schema type fails when data is a dict."""
        register_port_type(
            "array-only",
            json_schema={"type": "array", "items": {"type": "string"}},
        )
        valid, error = validate_port_data({"key": "val"}, "array-only")
        assert valid is False
        assert "does not match schema" in error

    def test_required_fields_check_passes(self) -> None:
        """Object with required fields passes when all present."""
        register_port_type(
            "required-fields-pass",
            json_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
                "required": ["name", "age"],
            },
        )
        valid, error = validate_port_data({"name": "Alice", "age": 30}, "required-fields-pass")
        assert valid is True
        assert error == ""

    def test_required_fields_check_fails_when_missing(self) -> None:
        """Object with required fields fails when a required field is missing."""
        register_port_type(
            "required-fields-fail",
            json_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                "required": ["name", "email"],
            },
        )
        valid, error = validate_port_data({"name": "Bob"}, "required-fields-fail")
        assert valid is False
        assert "does not match schema" in error

    def test_no_schema_registered_passes(self) -> None:
        """Type with no schema always passes validation."""
        valid, error = validate_port_data({"anything": "goes"}, "text")
        assert valid is True
        assert error == ""

    def test_schema_with_no_json_schema_passes(self) -> None:
        """Registered type with json_schema=None passes validation."""
        register_port_type("no-schema-type", json_schema=None, description="No schema")
        valid, error = validate_port_data({"data": 123}, "no-schema-type")
        assert valid is True
        assert error == ""


# ======================================================================
# Port types: get_composite_ports when block is None (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.33")
class TestCompositePortsUnknownBlock:
    """get_composite_ports skips blocks unknown to registry."""

    def test_composite_ports_with_unknown_block_type(self) -> None:
        """Unknown block types are skipped gracefully."""
        registry = BlockRegistry()
        team = TeamDef(
            name="partial-team",
            blocks={"known": "coder", "unknown": "not_registered_type"},
            connections=[],
            entry_block="known",
        )
        inputs, outputs = get_composite_ports(team, registry)
        # Should still get ports from the known block (coder)
        input_names = [p.name for p in inputs]
        assert "spec" in input_names or "context" in input_names
