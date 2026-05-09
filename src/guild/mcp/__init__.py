"""MCP (Model Context Protocol) client support for Guild.

Provides connectivity to MCP tool servers via stdio (subprocess) transport,
enabling agents to use external tools exposed over the MCP protocol.
"""

from guild.mcp.client import MCPClient, MCPError, MCPServerConfig, MCPTool
from guild.mcp.registry import MCPToolRegistry

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPServerConfig",
    "MCPTool",
    "MCPToolRegistry",
]
