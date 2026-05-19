"""File operation tools — read and write files."""

from __future__ import annotations

from typing import Any

from logger_python import get_logger

from guild.config.constants import MAX_FILE_READ_CHARS
from guild.tools.base import ToolResult, resolve_path

__all__ = ["MAX_FILE_READ_CHARS", "execute_file_read", "execute_file_write"]

logger = get_logger(__name__)


async def execute_file_read(args: dict[str, Any], working_dir: str | None = None) -> ToolResult:
    """Read a file and return its contents.

    Truncates files exceeding MAX_FILE_READ_CHARS. Handles binary files
    gracefully using errors="replace".
    """
    path_str = args.get("path", "")
    if not path_str:
        return ToolResult(success=False, output="", error="Missing required argument: path")

    path = resolve_path(path_str, working_dir)

    if not path.exists():
        return ToolResult(success=False, output="", error=f"File not found: {path}")

    if not path.is_file():
        return ToolResult(success=False, output="", error=f"Not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Failed to read file %s: %s", path, e)
        return ToolResult(success=False, output="", error=f"Cannot read file: {e}")

    if len(content) > MAX_FILE_READ_CHARS:
        content = content[:MAX_FILE_READ_CHARS] + "\n\n[Truncated — file exceeds limit]"

    return ToolResult(success=True, output=content)


async def execute_file_write(args: dict[str, Any], working_dir: str | None = None) -> ToolResult:
    """Write content to a file, creating parent directories as needed."""
    path_str = args.get("path", "")
    if not path_str:
        return ToolResult(success=False, output="", error="Missing required argument: path")

    content = args.get("content")
    if content is None:
        return ToolResult(success=False, output="", error="Missing required argument: content")

    path = resolve_path(path_str, working_dir)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.debug("Failed to write file %s: %s", path, e)
        return ToolResult(success=False, output="", error=f"Cannot write file: {e}")

    chars_written = len(content)
    return ToolResult(
        success=True,
        output=f"Wrote {chars_written} chars to {path}",
    )
