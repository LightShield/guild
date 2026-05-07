"""Port type system for block connectors."""

__all__ = [
    "PORT_TYPES",
    "check_port_compatibility",
    "register_port_type",
]

# Built-in port type tags
PORT_TYPES: set[str] = {
    "plan",
    "code-changes",
    "review",
    "test-results",
    "text",
    "files",
    "any",
}


def check_port_compatibility(source_type: str, target_type: str) -> bool:
    """Check if two port types are compatible.

    'any' is compatible with everything.
    Otherwise types must match exactly.
    """
    if source_type == "any" or target_type == "any":
        return True
    return source_type == target_type


def register_port_type(type_tag: str) -> None:
    """Register a new custom port type."""
    PORT_TYPES.add(type_tag)
