"""Search and glob tools — find content and files (REQ-08.3)."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any

from guild.tools.base import ToolResult, resolve_path

__all__ = [
    "MAX_GLOB_RESULTS",
    "MAX_SEARCH_RESULTS",
    "execute_glob",
    "execute_search",
]

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS: int = 200
MAX_GLOB_RESULTS: int = 500

# Directories to always skip during traversal.
_SKIP_DIRS: set[str] = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _should_skip_dir(name: str) -> bool:
    """Return True if directory should be skipped."""
    return name in _SKIP_DIRS


async def execute_search(args: dict[str, Any], working_dir: str | None = None) -> ToolResult:
    """Search files for lines matching a regex pattern.

    Args:
        args: Must contain "pattern" and "path". Optional "include" glob filter.
        working_dir: Base directory for relative paths.

    Returns:
        ToolResult with matching lines or error.
    """
    pattern_str = args.get("pattern", "")
    if not pattern_str:
        return ToolResult(success=False, output="", error="Missing required argument: pattern")

    path_str = args.get("path", ".")
    search_path = resolve_path(path_str, working_dir)

    if not search_path.exists():
        return ToolResult(success=False, output="", error=f"Path not found: {search_path}")

    try:
        compiled = re.compile(pattern_str)
    except re.error as e:
        return ToolResult(success=False, output="", error=f"Invalid regex pattern: {e}")

    include_filter = args.get("include")
    matches = _collect_search_matches(search_path, compiled, include_filter)

    if not matches:
        return ToolResult(success=True, output="No matches found.")

    truncated = len(matches) > MAX_SEARCH_RESULTS
    matches = matches[:MAX_SEARCH_RESULTS]

    output = "\n".join(matches)
    if truncated:
        output += f"\n\n[Truncated — results limited to {MAX_SEARCH_RESULTS}]"

    return ToolResult(success=True, output=output)


def _collect_search_matches(
    search_path: Path,
    pattern: re.Pattern[str],
    include_filter: str | None,
) -> list[str]:
    """Walk directory tree and collect matching lines."""
    matches: list[str] = []

    if search_path.is_file():
        _search_file(search_path, pattern, search_path.parent, matches)
        return matches

    for dirpath, dirnames, filenames in os.walk(search_path):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for filename in filenames:
            if include_filter and not fnmatch.fnmatch(filename, include_filter):
                continue

            filepath = Path(dirpath) / filename
            _search_file(filepath, pattern, search_path, matches)

            if len(matches) > MAX_SEARCH_RESULTS:
                return matches

    return matches


def _search_file(
    filepath: Path,
    pattern: re.Pattern[str],
    base_path: Path,
    matches: list[str],
) -> None:
    """Search a single file for pattern matches."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    rel_path = filepath.relative_to(base_path) if _is_relative_to(filepath, base_path) else filepath

    for line_no, line in enumerate(content.splitlines(), start=1):
        if pattern.search(line):
            matches.append(f"{rel_path}:{line_no}: {line}")
            if len(matches) > MAX_SEARCH_RESULTS:
                return


def _is_relative_to(path: Path, base: Path) -> bool:
    """Check if path is relative to base (compat with Python 3.11)."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


async def execute_glob(args: dict[str, Any], working_dir: str | None = None) -> ToolResult:
    """Find files matching a glob pattern.

    Args:
        args: Must contain "pattern". Optional "path" for search root.
        working_dir: Base directory for relative paths.

    Returns:
        ToolResult with list of matching file paths.
    """
    pattern_str = args.get("pattern", "")
    if not pattern_str:
        return ToolResult(success=False, output="", error="Missing required argument: pattern")

    path_str = args.get("path", ".")
    search_path = resolve_path(path_str, working_dir)

    if not search_path.exists():
        return ToolResult(success=False, output="", error=f"Path not found: {search_path}")

    results = _collect_glob_matches(search_path, pattern_str)

    if not results:
        return ToolResult(success=True, output="No files found matching pattern.")

    truncated = len(results) > MAX_GLOB_RESULTS
    results = results[:MAX_GLOB_RESULTS]

    output = "\n".join(results)
    if truncated:
        output += f"\n\n[Truncated — results limited to {MAX_GLOB_RESULTS}]"

    return ToolResult(success=True, output=output)


def _collect_glob_matches(search_path: Path, pattern: str) -> list[str]:
    """Collect glob matches, skipping hidden directories."""
    all_matches: list[str] = []

    for match in search_path.glob(pattern):
        parts = match.relative_to(search_path).parts
        if any(_should_skip_dir(part) for part in parts):
            continue

        rel = str(match.relative_to(search_path))
        all_matches.append(rel)

        if len(all_matches) > MAX_GLOB_RESULTS:
            break

    return all_matches
