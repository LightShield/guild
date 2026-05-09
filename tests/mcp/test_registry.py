"""Tests for mcp/registry.py — MCP tool registry (REQ-04.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from guild.mcp.client import MCPClient, MCPServerConfig, MCPTool
from guild.mcp.registry import MCPToolRegistry


def _make_tool(name: str, server: str = "test-server") -> MCPTool:
    """Create a test MCPTool."""
    return MCPTool(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object", "properties": {}},
        server_name=server,
    )


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPToolRegistryAddServer:
    """Tests for MCPToolRegistry.add_server()."""

    async def test_add_server_connects_and_lists_tools(self) -> None:
        """add_server() connects to the server and registers its tools."""
        registry = MCPToolRegistry()
        config = MCPServerConfig(name="fs", command="npx", args=["server"])

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(MCPClient, "list_tools", new_callable=AsyncMock) as mock_list,
        ):
            mock_list.return_value = [
                _make_tool("read_file", "fs"),
                _make_tool("write_file", "fs"),
            ]
            tools = await registry.add_server(config)

        mock_connect.assert_awaited_once()
        mock_list.assert_awaited_once()
        assert len(tools) == 2
        assert registry.get_tool("read_file") is not None
        assert registry.get_tool("write_file") is not None


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPToolRegistryRemoveServer:
    """Tests for MCPToolRegistry.remove_server()."""

    async def test_remove_server_disconnects(self) -> None:
        """remove_server() disconnects the client and removes tools."""
        registry = MCPToolRegistry()
        config = MCPServerConfig(name="fs", command="npx", args=["server"])

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock),
            patch.object(MCPClient, "list_tools", new_callable=AsyncMock) as mock_list,
        ):
            mock_list.return_value = [_make_tool("read_file", "fs")]
            await registry.add_server(config)

        with patch.object(MCPClient, "disconnect", new_callable=AsyncMock) as mock_disconnect:
            await registry.remove_server("fs")

        mock_disconnect.assert_awaited_once()
        assert registry.get_tool("read_file") is None


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPToolRegistryCallTool:
    """Tests for MCPToolRegistry.call_tool() — routing."""

    async def test_call_routes_to_correct_server(self) -> None:
        """call_tool() routes the call to the server that owns the tool."""
        registry = MCPToolRegistry()
        config_a = MCPServerConfig(name="server-a", command="a", args=[])
        config_b = MCPServerConfig(name="server-b", command="b", args=[])

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock),
            patch.object(MCPClient, "list_tools", new_callable=AsyncMock) as mock_list,
        ):
            mock_list.return_value = [_make_tool("tool_a", "server-a")]
            await registry.add_server(config_a)

            mock_list.return_value = [_make_tool("tool_b", "server-b")]
            await registry.add_server(config_b)

        expected_result = {"content": [{"type": "text", "text": "result"}]}
        with patch.object(MCPClient, "call_tool", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = expected_result
            result = await registry.call_tool("tool_b", {"arg": "val"})

        mock_call.assert_awaited_once_with("tool_b", {"arg": "val"})
        assert result == expected_result


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPToolRegistrySchemas:
    """Tests for MCPToolRegistry.to_tool_schemas()."""

    async def test_to_tool_schemas_exports_for_llm(self) -> None:
        """to_tool_schemas() returns schemas suitable for LLM tool use."""
        registry = MCPToolRegistry()
        config = MCPServerConfig(name="fs", command="npx", args=["server"])

        tool = MCPTool(
            name="read_file",
            description="Read a file",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            server_name="fs",
        )

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock),
            patch.object(MCPClient, "list_tools", new_callable=AsyncMock) as mock_list,
        ):
            mock_list.return_value = [tool]
            await registry.add_server(config)

        schemas = registry.to_tool_schemas()

        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "read_file"
        assert schema["function"]["description"] == "Read a file"
        assert schema["function"]["parameters"]["type"] == "object"
        assert "path" in schema["function"]["parameters"]["properties"]


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPToolRegistryDisconnectAll:
    """Tests for MCPToolRegistry.disconnect_all()."""

    async def test_disconnect_all_cleans_up(self) -> None:
        """disconnect_all() disconnects all servers and clears state."""
        registry = MCPToolRegistry()
        config_a = MCPServerConfig(name="server-a", command="a", args=[])
        config_b = MCPServerConfig(name="server-b", command="b", args=[])

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock),
            patch.object(MCPClient, "list_tools", new_callable=AsyncMock) as mock_list,
        ):
            mock_list.return_value = [_make_tool("tool_a", "server-a")]
            await registry.add_server(config_a)

            mock_list.return_value = [_make_tool("tool_b", "server-b")]
            await registry.add_server(config_b)

        with patch.object(MCPClient, "disconnect", new_callable=AsyncMock) as mock_disconnect:
            await registry.disconnect_all()

        assert mock_disconnect.await_count == 2
        assert registry.list_all_tools() == []
