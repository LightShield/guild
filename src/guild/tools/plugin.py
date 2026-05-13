"""Plugin-based tool system with MCP-native schemas and caching.

REQ-08.8: MCP-native tool interface — tools expose MCP-compatible schemas.
REQ-08.9: Plugin-based tool loading — file-per-tool or directory-per-tool.
REQ-08.10: Tool behavioral properties: isConcurrencySafe, isReadOnly.
REQ-08.11: Tool result caching (optional, per-tool).
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable
    from pathlib import Path

    from guild.tools.base import ToolResult

__all__ = [
    "DEFAULT_CACHE_MAX_SIZE",
    "DEFAULT_CACHE_TTL_SECONDS",
    "PluginLoader",
    "ToolCache",
    "ToolPlugin",
    "ToolProperties",
]

logger = logging.getLogger(__name__)

# Named constants for cache configuration
DEFAULT_CACHE_TTL_SECONDS: int = 300
DEFAULT_CACHE_MAX_SIZE: int = 100


@dataclass
class ToolProperties:
    """Behavioral properties for tool optimization (REQ-08.10)."""

    is_read_only: bool = False
    is_concurrency_safe: bool = True
    cacheable: bool = False
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS


@dataclass
class ToolPlugin:
    """A loadable tool plugin definition."""

    name: str
    description: str
    parameters: dict[str, Any]
    properties: ToolProperties = field(default_factory=ToolProperties)
    executor: Callable[..., Any] | None = None

    def to_mcp_schema(self) -> dict[str, Any]:
        """Export as MCP-compatible tool schema (REQ-08.8)."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters,
        }


@dataclass
class _CacheEntry:
    """Internal cache entry with expiration tracking."""

    result: ToolResult
    expires_at: float


class ToolCache:
    """LRU cache for cacheable tool results (REQ-08.11)."""

    def __init__(self, max_size: int = DEFAULT_CACHE_MAX_SIZE) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

    def get(self, key: str) -> ToolResult | None:
        """Retrieve a cached result, returning None if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry.expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return entry.result

    def put(self, key: str, result: ToolResult, ttl: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        """Store a result with a TTL in seconds."""
        expires_at = time.time() + ttl
        if key in self._store:
            self._store[key] = _CacheEntry(result=result, expires_at=expires_at)
            self._store.move_to_end(key)
        else:
            self._store[key] = _CacheEntry(result=result, expires_at=expires_at)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def invalidate(self, key: str | None = None) -> None:
        """Remove a specific key, or clear all entries if key is None."""
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)


class PluginLoader:
    """Discovers and loads tool plugins from directories (REQ-08.9)."""

    def __init__(self, plugin_dirs: list[Path]) -> None:
        self._plugin_dirs = plugin_dirs

    def discover(self) -> list[ToolPlugin]:
        """Discover all plugins across all configured directories."""
        plugins: list[ToolPlugin] = []
        for directory in self._plugin_dirs:
            if directory.is_dir():
                plugins.extend(self.load_from_dir(directory))
        return plugins

    def load_from_file(self, path: Path) -> ToolPlugin | None:
        """Load a single plugin from a TOML file. Returns None on failure."""
        try:
            import tomllib
        except ImportError:  # pragma: no cover — Python 3.10 compat
            import tomli as tomllib  # type: ignore[no-redef, import-not-found]

        try:
            content = path.read_text(encoding="utf-8")
            data = tomllib.loads(content)
        except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError):
            logger.debug("Failed to load %s", path, exc_info=True)
            return None

        tool_section = data.get("tool")
        if not tool_section or not isinstance(tool_section, dict):
            logger.warning("Plugin file missing [tool] section: %s", path)
            return None

        name = tool_section.get("name")
        description = tool_section.get("description", "")
        if not name:
            logger.warning("Plugin file missing tool.name: %s", path)
            return None

        parameters = self._parse_parameters(tool_section.get("parameters", {}))

        properties = ToolProperties(
            is_read_only=tool_section.get("is_read_only", False),
            is_concurrency_safe=tool_section.get("is_concurrency_safe", True),
            cacheable=tool_section.get("cacheable", False),
            cache_ttl_seconds=tool_section.get("cache_ttl_seconds", DEFAULT_CACHE_TTL_SECONDS),
        )

        return ToolPlugin(
            name=name,
            description=description,
            parameters=parameters,
            properties=properties,
        )

    def load_from_dir(self, path: Path) -> list[ToolPlugin]:
        """Load all .toml plugin files from a directory."""
        plugins: list[ToolPlugin] = []
        if not path.is_dir():
            return plugins
        for toml_file in sorted(path.glob("*.toml")):
            plugin = self.load_from_file(toml_file)
            if plugin is not None:
                plugins.append(plugin)
        return plugins

    def _parse_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        """Parse and normalize the parameters section from TOML."""
        result: dict[str, Any] = {}
        result["type"] = params.get("type", "object")

        raw_properties = params.get("properties", {})
        if raw_properties:
            result["properties"] = raw_properties

        raw_required = params.get("required", {})
        if isinstance(raw_required, dict) and "list" in raw_required:
            result["required"] = raw_required["list"]
        elif isinstance(raw_required, list):
            result["required"] = raw_required

        return result
