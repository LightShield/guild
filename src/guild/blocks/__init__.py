"""Composable block system for agent teams."""

from .definition import BlockDef, Connection, LoopDef, PortDef, TeamDef
from .port_types import (
    PORT_TYPES,
    check_port_compatibility,
    register_port_type,
)
from .registry import BlockRegistry

__all__ = [
    "PORT_TYPES",
    "BlockDef",
    "BlockRegistry",
    "Connection",
    "LoopDef",
    "PortDef",
    "TeamDef",
    "check_port_compatibility",
    "register_port_type",
]
