"""Tool infrastructure — result type, schemas, and path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["ToolResult", "TOOL_SCHEMAS", "resolve_path"]


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    output: str
    error: str | None = None

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"Error: {self.error}"


def resolve_path(path_str: str, working_dir: str | None) -> Path:
    """Resolve a path string to an absolute Path.

    Relative paths are resolved against working_dir.
    Absolute paths are returned unchanged.
    """
    path = Path(path_str)
    if path.is_absolute():
        return path
    if working_dir:
        return Path(working_dir) / path
    return path.resolve()


TOOL_SCHEMAS: dict[str, dict] = {
    "file_read": {
        "name": "file_read",
        "description": "Read the contents of a file at the given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute).",
                },
            },
            "required": ["path"],
        },
    },
    "file_write": {
        "name": "file_write",
        "description": "Write content to a file, creating parent directories as needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write (relative or absolute).",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    "shell": {
        "name": "shell",
        "description": (
            "Execute a shell command. SAFETY: Dangerous commands are automatically "
            "blocked by a denylist (rm -rf /, sudo rm, git push --force, git reset "
            "--hard, fork bombs, mkfs, dd to devices, curl|bash). Commands that are "
            "denied will return an error. Commands are subject to a timeout (default "
            "60s). Output is truncated at 20000 characters."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 60).",
                },
            },
            "required": ["command"],
        },
    },
    "search": {
        "name": "search",
        "description": (
            "Search file contents for lines matching a regex pattern. "
            "Skips .git, __pycache__, and node_modules directories. "
            "Results limited to 200 matches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search (default: working dir).",
                },
                "include": {
                    "type": "string",
                    "description": "Glob filter for filenames (e.g. '*.py').",
                },
            },
            "required": ["pattern"],
        },
    },
    "glob": {
        "name": "glob",
        "description": (
            "Find files matching a glob pattern. Skips .git, __pycache__, "
            "and node_modules directories. Results limited to 500 files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py').",
                },
                "path": {
                    "type": "string",
                    "description": "Root directory for search (default: working dir).",
                },
            },
            "required": ["pattern"],
        },
    },
}
