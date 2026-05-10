"""Central tool executor registry — single source of truth for tool mappings.

Every call site that needs the standard tool executor dict should use
``build_tool_executors()`` instead of assembling its own inline dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from guild.tools.file_ops import execute_file_read, execute_file_write
from guild.tools.search import execute_glob, execute_search
from guild.tools.shell import execute_shell

__all__ = ["build_tool_executors"]


def build_tool_executors() -> dict[str, Callable[..., Any]]:
    """Build the standard tool executor dict. Single source of truth."""
    return {
        "file_read": execute_file_read,
        "file_write": execute_file_write,
        "shell": execute_shell,
        "search": execute_search,
        "glob": execute_glob,
    }
