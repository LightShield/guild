"""Tests for plugin-based tool system (REQ-08.8, REQ-08.9, REQ-08.10, REQ-08.11).

REQ-08.8: MCP-native tool interface — tools expose MCP-compatible schemas.
REQ-08.9: Plugin-based tool loading — file-per-tool or directory-per-tool.
REQ-08.10: Tool behavioral properties: isConcurrencySafe, isReadOnly.
REQ-08.11: Tool result caching (optional, per-tool).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from guild.tools.base import ToolResult
from guild.tools.plugin import PluginLoader, ToolCache, ToolPlugin, ToolProperties

if TYPE_CHECKING:
    from pathlib import Path


# --- REQ-08.8: MCP-native tool interface ---


@pytest.mark.unit
@pytest.mark.req("REQ-08.8")
class TestMCPSchema:
    """Tools expose MCP-compatible schemas."""

    def test_tool_plugin_exports_mcp_schema(self) -> None:
        """ToolPlugin.to_mcp_schema() returns a dict with MCP structure."""
        plugin = ToolPlugin(
            name="test_tool",
            description="A test tool",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        )
        schema = plugin.to_mcp_schema()
        assert isinstance(schema, dict)
        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"
        assert schema["inputSchema"] == plugin.parameters

    def test_mcp_schema_has_required_fields(self) -> None:
        """MCP schema must contain name, description, and inputSchema."""
        plugin = ToolPlugin(
            name="another_tool",
            description="Another tool",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        schema = plugin.to_mcp_schema()
        assert "name" in schema
        assert "description" in schema
        assert "inputSchema" in schema
        # inputSchema must have type "object"
        assert schema["inputSchema"]["type"] == "object"


# --- REQ-08.9: Plugin-based tool loading ---


@pytest.mark.unit
@pytest.mark.req("REQ-08.9")
class TestPluginLoading:
    """Discovers and loads tool plugins from directories."""

    def test_discover_plugins_from_directory(self, tmp_path: Path) -> None:
        """PluginLoader.discover() finds .toml plugin files in directories."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        # Create two plugin files
        (plugin_dir / "tool_a.toml").write_text(
            "[tool]\n"
            'name = "tool_a"\n'
            'description = "Tool A"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            "\n"
            "[tool.parameters.properties.input]\n"
            'type = "string"\n'
            'description = "Input value"\n'
        )
        (plugin_dir / "tool_b.toml").write_text(
            "[tool]\n"
            'name = "tool_b"\n'
            'description = "Tool B"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            "\n"
            "[tool.parameters.properties.data]\n"
            'type = "string"\n'
            'description = "Data value"\n'
        )
        # Also a non-toml file that should be ignored
        (plugin_dir / "readme.txt").write_text("ignore me")

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugins = loader.discover()
        assert len(plugins) == 2
        names = {p.name for p in plugins}
        assert names == {"tool_a", "tool_b"}

    def test_load_plugin_from_toml_file(self, tmp_path: Path) -> None:
        """PluginLoader.load_from_file() parses a valid TOML plugin."""
        plugin_file = tmp_path / "my_tool.toml"
        plugin_file.write_text(
            "[tool]\n"
            'name = "my_tool"\n'
            'description = "Does something useful"\n'
            "is_read_only = true\n"
            "cacheable = true\n"
            "cache_ttl_seconds = 600\n"
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            "\n"
            "[tool.parameters.properties.query]\n"
            'type = "string"\n'
            'description = "The query"\n'
            "\n"
            "[tool.parameters.required]\n"
            'list = ["query"]\n'
        )

        loader = PluginLoader(plugin_dirs=[tmp_path])
        plugin = loader.load_from_file(plugin_file)
        assert plugin is not None
        assert plugin.name == "my_tool"
        assert plugin.description == "Does something useful"
        assert plugin.properties.is_read_only is True
        assert plugin.properties.cacheable is True
        assert plugin.properties.cache_ttl_seconds == 600

    def test_load_returns_none_for_invalid_file(self, tmp_path: Path) -> None:
        """PluginLoader.load_from_file() returns None for malformed files."""
        bad_file = tmp_path / "broken.toml"
        bad_file.write_text("this is not valid toml [[[")

        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(bad_file)
        assert result is None

    def test_load_from_dir_discovers_subdirectory_plugins(self, tmp_path: Path) -> None:
        """PluginLoader.load_from_dir() loads plugins from a directory."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "sub_tool.toml").write_text(
            "[tool]\n"
            'name = "sub_tool"\n'
            'description = "Sub tool"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            "\n"
            "[tool.parameters.properties.x]\n"
            'type = "integer"\n'
            'description = "A number"\n'
        )

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugins = loader.load_from_dir(plugin_dir)
        assert len(plugins) == 1
        assert plugins[0].name == "sub_tool"


# --- REQ-08.10: Tool behavioral properties ---


@pytest.mark.unit
@pytest.mark.req("REQ-08.10")
class TestToolProperties:
    """Tools declare behavioral properties for optimization."""

    def test_tool_properties_defaults(self) -> None:
        """ToolProperties defaults: not read-only, concurrency-safe, not cached."""
        props = ToolProperties()
        assert props.is_read_only is False
        assert props.is_concurrency_safe is True
        assert props.cacheable is False
        assert props.cache_ttl_seconds == 300

    def test_read_only_tool_flagged(self) -> None:
        """A tool marked is_read_only=True reports correctly."""
        props = ToolProperties(is_read_only=True)
        assert props.is_read_only is True

    def test_concurrency_safe_flagged(self) -> None:
        """A tool with is_concurrency_safe=False reports correctly."""
        props = ToolProperties(is_concurrency_safe=False)
        assert props.is_concurrency_safe is False


# --- REQ-08.11: Tool result caching ---


@pytest.mark.unit
@pytest.mark.req("REQ-08.11")
class TestToolCache:
    """LRU cache for cacheable tool results."""

    def test_cache_stores_and_retrieves(self) -> None:
        """Cache.put() stores a result, Cache.get() retrieves it."""
        cache = ToolCache(max_size=10)
        result = ToolResult(success=True, output="cached data")
        cache.put("key1", result, ttl=300)
        retrieved = cache.get("key1")
        assert retrieved is not None
        assert retrieved.output == "cached data"
        assert retrieved.success is True

    def test_cache_expires_after_ttl(self) -> None:
        """Entries expire after their TTL elapses."""
        cache = ToolCache(max_size=10)
        result = ToolResult(success=True, output="ephemeral")
        cache.put("key2", result, ttl=1)
        # Simulate time passing
        time.sleep(1.1)
        retrieved = cache.get("key2")
        assert retrieved is None

    def test_cache_invalidate_clears(self) -> None:
        """Cache.invalidate() removes a specific key or all entries."""
        cache = ToolCache(max_size=10)
        r1 = ToolResult(success=True, output="one")
        r2 = ToolResult(success=True, output="two")
        cache.put("a", r1, ttl=300)
        cache.put("b", r2, ttl=300)

        # Invalidate specific key
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") is not None

        # Invalidate all
        cache.invalidate(None)
        assert cache.get("b") is None

    def test_cache_respects_max_size(self) -> None:
        """Cache evicts oldest entries when max_size is exceeded."""
        cache = ToolCache(max_size=3)
        for i in range(5):
            cache.put(f"key{i}", ToolResult(success=True, output=f"val{i}"), ttl=300)

        # Oldest entries (key0, key1) should be evicted
        assert cache.get("key0") is None
        assert cache.get("key1") is None
        # Newest entries should remain
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None


# ======================================================================
# Plugin loader edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.9")
class TestPluginLoaderEdgeCases:
    """Cover plugin loader edge cases."""

    def test_discover_skips_non_directory(self, tmp_path: Path) -> None:
        """discover() skips paths that aren't directories."""
        from guild.tools.plugin import PluginLoader

        fake_path = tmp_path / "not-a-dir"
        loader = PluginLoader(plugin_dirs=[fake_path])
        plugins = loader.discover()
        assert plugins == []

    def test_load_from_file_invalid_toml(self, tmp_path: Path) -> None:
        """load_from_file returns None for invalid TOML."""
        from guild.tools.plugin import PluginLoader

        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("this is not valid toml [[[")
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(bad_file)
        assert result is None

    def test_load_from_file_no_tool_section(self, tmp_path: Path) -> None:
        """load_from_file returns None when [tool] section missing."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "no_tool.toml"
        f.write_text('[other]\nkey = "value"\n')
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(f)
        assert result is None

    def test_load_from_file_no_tool_name(self, tmp_path: Path) -> None:
        """load_from_file returns None when tool.name is missing."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "no_name.toml"
        f.write_text('[tool]\ndescription = "no name"\n')
        loader = PluginLoader(plugin_dirs=[tmp_path])
        result = loader.load_from_file(f)
        assert result is None

    def test_load_from_dir_nonexistent(self, tmp_path: Path) -> None:
        """load_from_dir returns empty for non-directory."""
        from guild.tools.plugin import PluginLoader

        loader = PluginLoader(plugin_dirs=[tmp_path / "nope"])
        result = loader.load_from_dir(tmp_path / "nope")
        assert result == []

    def test_cache_update_existing_key(self) -> None:
        """ToolCache.put updates an existing key and moves to end."""
        from guild.tools.base import ToolResult
        from guild.tools.plugin import ToolCache

        cache = ToolCache(max_size=5)
        r1 = ToolResult(success=True, output="first")
        r2 = ToolResult(success=True, output="second")
        cache.put("key1", r1)
        cache.put("key1", r2)  # Update existing
        result = cache.get("key1")
        assert result is not None
        assert result.output == "second"

    def test_cache_evicts_oldest_when_full(self) -> None:
        """ToolCache evicts oldest entries when at capacity."""
        from guild.tools.base import ToolResult
        from guild.tools.plugin import ToolCache

        cache = ToolCache(max_size=2)
        cache.put("k1", ToolResult(success=True, output="1"))
        cache.put("k2", ToolResult(success=True, output="2"))
        cache.put("k3", ToolResult(success=True, output="3"))
        # k1 should be evicted
        assert cache.get("k1") is None
        assert cache.get("k2") is not None
        assert cache.get("k3") is not None

    def test_parse_parameters_with_required_dict(self, tmp_path: Path) -> None:
        """Parser handles required as a dict with 'list' key."""
        from guild.tools.plugin import PluginLoader

        f = tmp_path / "tool.toml"
        f.write_text(
            "[tool]\n"
            'name = "my-tool"\n'
            'description = "Test tool"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            "\n"
            "[tool.parameters.properties.arg1]\n"
            'type = "string"\n'
            "\n"
            "[tool.parameters.required]\n"
            'list = ["arg1"]\n'
        )
        loader = PluginLoader(plugin_dirs=[tmp_path])
        plugin = loader.load_from_file(f)
        assert plugin is not None
        assert plugin.parameters.get("required") == ["arg1"]


# ======================================================================
# Tools/plugin additional edges (from coverage gaps)
# ======================================================================


@pytest.mark.req("REQ-06.1")
@pytest.mark.unit
class TestToolsPluginEdges:
    """Cover tools/plugin.py uncovered branches."""

    def test_plugin_load_from_file_missing_name(self, tmp_path: Path) -> None:
        """Plugin without tool.name returns None (line 199 path)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "no_name.toml"
        # Valid TOML with [tool] section but no name field
        plugin_file.write_text("[tool]\n" 'description = "A tool without a name"\n')

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        result = loader.load_from_file(plugin_file)
        assert result is None

    def test_plugin_load_from_file_no_tool_section(self, tmp_path: Path) -> None:
        """Plugin without [tool] section returns None."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin_file = plugin_dir / "no_section.toml"
        plugin_file.write_text('[metadata]\nauthor = "test"\n')

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        result = loader.load_from_file(plugin_file)
        assert result is None

    def test_plugin_load_from_dir_skips_none(self, tmp_path: Path) -> None:
        """load_from_dir skips files that return None (line 180->178)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        # One bad plugin
        (plugin_dir / "bad.toml").write_text("[metadata]\n")
        # One good plugin
        (plugin_dir / "good.toml").write_text(
            "[tool]\n" 'name = "good_tool"\n' 'description = "A good tool"\n'
        )

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugins = loader.load_from_dir(plugin_dir)
        # Only the good one should load
        assert len(plugins) == 1
        assert plugins[0].name == "good_tool"

    def test_plugin_parameters_required_as_list(self, tmp_path: Path) -> None:
        """Plugin with required as a list parses directly (line 199)."""
        from guild.tools.plugin import PluginLoader

        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        # TOML with required as a direct list
        (plugin_dir / "with_required.toml").write_text(
            "[tool]\n"
            'name = "my_tool"\n'
            'description = "test"\n'
            "\n"
            "[tool.parameters]\n"
            'type = "object"\n'
            'required = ["path", "content"]\n'
        )

        loader = PluginLoader(plugin_dirs=[plugin_dir])
        plugin = loader.load_from_file(plugin_dir / "with_required.toml")
        assert plugin is not None
        assert plugin.parameters.get("required") == ["path", "content"]
