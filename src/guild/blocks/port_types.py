"""Port type system for block connectors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from guild.blocks.definition import PortDef, TeamDef
    from guild.blocks.registry import BlockRegistry

__all__ = [
    "PORT_TYPE_ANY",
    "PORT_TYPE_REGISTRY",
    "PORT_TYPES",
    "PortTypeSchema",
    "check_port_compatibility",
    "get_composite_ports",
    "register_port_type",
    "validate_port_data",
]

PORT_TYPE_ANY = "any"


@dataclass
class PortTypeSchema:
    """Full port type definition with optional JSON schema."""

    type_tag: str
    json_schema: dict | None = None
    description: str = ""


# Registry of port types with schemas
PORT_TYPE_REGISTRY: dict[str, PortTypeSchema] = {}

# Built-in port type tags (kept for backward compat)
PORT_TYPES: set[str] = {
    "plan",
    "code-changes",
    "review",
    "test-results",
    "text",
    "files",
    PORT_TYPE_ANY,
}


def register_port_type(
    type_tag: str,
    json_schema: dict | None = None,
    description: str = "",
) -> None:
    """Register a new port type with optional schema."""
    PORT_TYPES.add(type_tag)
    PORT_TYPE_REGISTRY[type_tag] = PortTypeSchema(
        type_tag=type_tag,
        json_schema=json_schema,
        description=description,
    )


def check_port_compatibility(source_type: str, target_type: str) -> bool:
    """Check if two port types are compatible.

    'any' is compatible with everything.
    Otherwise types must match exactly.
    """
    if source_type == PORT_TYPE_ANY or target_type == PORT_TYPE_ANY:
        return True
    return source_type == target_type


def validate_port_data(data: dict, type_tag: str) -> tuple[bool, str]:
    """Validate port data against type schema.

    Returns (valid, error_message). Empty error_message on success.
    All port data must be JSON-serializable (REQ-04.35).
    """
    try:
        json.dumps(data)
    except (TypeError, ValueError) as e:
        return False, f"Data not JSON-serializable: {e}"

    schema_entry = PORT_TYPE_REGISTRY.get(type_tag)
    if schema_entry is None or schema_entry.json_schema is None:
        return True, ""

    # Basic schema validation (type check at top level)
    schema = schema_entry.json_schema
    if not _basic_schema_check(data, schema):
        return False, f"Data does not match schema for type '{type_tag}'"

    return True, ""


def _basic_schema_check(data: object, schema: dict) -> bool:
    """Perform basic JSON schema validation (top-level type + required)."""
    schema_type = schema.get("type")
    if schema_type == "object" and not isinstance(data, dict):
        return False
    if schema_type == "array" and not isinstance(data, list):
        return False

    if isinstance(data, dict) and schema_type == "object":
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                return False

    return True


def get_composite_ports(
    team: TeamDef, registry: BlockRegistry
) -> tuple[list[PortDef], list[PortDef]]:
    """Get exposed ports of a composite block (unconnected inner ports).

    Inputs: inner block input ports that have no incoming connection.
    Outputs: inner block output ports that have no outgoing connection.
    """
    connected_inputs: set[tuple[str, str]] = set()
    connected_outputs: set[tuple[str, str]] = set()

    for conn in team.connections:
        connected_outputs.add((conn.source_block, conn.source_port))
        connected_inputs.add((conn.target_block, conn.target_port))

    exposed_inputs: list[PortDef] = []
    exposed_outputs: list[PortDef] = []

    for instance_name, block_type in team.blocks.items():
        block_def = registry.get_block(block_type)
        if block_def is None:
            continue

        for port in block_def.inputs:
            if (instance_name, port.name) not in connected_inputs:
                exposed_inputs.append(port)

        for port in block_def.outputs:
            if (instance_name, port.name) not in connected_outputs:
                exposed_outputs.append(port)

    return exposed_inputs, exposed_outputs
