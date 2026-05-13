"""MCP tool registry — manages connections to multiple MCP servers."""

from __future__ import annotations

import logging
from typing import Any

from guild.mcp.client import MCPClient, MCPServerConfig, MCPTool

__all__ = ["MCPToolRegistry"]

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """Manages connections to multiple MCP servers and their tools."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, MCPTool] = {}

    async def add_server(self, config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server and register its tools."""
        client = MCPClient(config)
        await client.connect()

        try:
            tools = await client.list_tools()
        except BaseException:
            await client.disconnect()
            raise

        self._clients[config.name] = client

        for tool in tools:
            self._tools[tool.name] = tool

        logger.debug(
            "Registered %d tools from MCP server %r",
            len(tools),
            config.name,
        )
        return tools

    async def remove_server(self, name: str) -> None:
        """Disconnect from a server and remove its tools."""
        client = self._clients.pop(name, None)
        if client is None:
            return

        await client.disconnect()

        # Remove tools belonging to this server
        self._tools = {k: v for k, v in self._tools.items() if v.server_name != name}
        logger.debug("Removed MCP server %r", name)

    def get_tool(self, name: str) -> MCPTool | None:
        """Get a registered MCP tool by name."""
        return self._tools.get(name)

    def list_all_tools(self) -> list[MCPTool]:
        """List all tools from all connected servers."""
        return list(self._tools.values())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by name, routing to the correct server."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool {name!r} not found in any MCP server")

        client = self._clients.get(tool.server_name)
        if client is None:
            raise KeyError(f"Server {tool.server_name!r} not connected")

        return await client.call_tool(name, arguments)

    def to_tool_schemas(self) -> list[dict[str, Any]]:
        """Export all MCP tools as schemas for the LLM."""
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for client in self._clients.values():
            await client.disconnect()
        server_count = len(self._clients)
        self._clients.clear()
        self._tools.clear()
        logger.debug("Disconnected from all MCP servers (count=%d)", server_count)
