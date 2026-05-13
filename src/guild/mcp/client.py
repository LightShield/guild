"""MCP client for communicating with tool servers via stdio.

Protocol: JSON-RPC 2.0 over stdin/stdout of a subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

__all__ = ["MCPClient", "MCPError", "MCPServerConfig", "MCPTool"]

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for connecting to an MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class MCPError(Exception):
    """Error from an MCP server."""


class MCPClient:
    """Client for communicating with MCP tool servers via stdio.

    Protocol: JSON-RPC 2.0 over stdin/stdout of a subprocess.
    """

    def __init__(self, server_config: MCPServerConfig) -> None:
        self._config = server_config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.disconnect()

    @property
    def config(self) -> MCPServerConfig:
        """Return the server configuration."""
        return self._config

    async def connect(self) -> None:
        """Start the MCP server subprocess."""
        cmd = [self._config.command, *self._config.args]
        env = {**os.environ, **self._config.env} if self._config.env else None

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        logger.debug("Connected to MCP server %r (pid=%s)", self._config.name, self._process.pid)

    async def disconnect(self) -> None:
        """Terminate the server subprocess."""
        if self._process is None:
            return
        self._process.terminate()
        await self._process.wait()
        logger.debug("Disconnected from MCP server %r", self._config.name)
        self._process = None

    async def list_tools(self) -> list[MCPTool]:
        """Request the list of available tools from the server."""
        response = await self._send_request("tools/list", {})
        tools: list[MCPTool] = []
        for tool_data in response.get("tools", []):
            tools.append(
                MCPTool(
                    name=tool_data["name"],
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=self._config.name,
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the server. Returns the result."""
        return await self._send_request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result."""
        if self._process is None or self._process.stdin is None:
            raise MCPError("Not connected to MCP server")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        line = json.dumps(request) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        if self._process.stdout is None:
            raise MCPError("Server stdout is not available")

        response_line = await self._process.stdout.readline()
        if not response_line:
            raise MCPError("Server closed connection unexpectedly")

        response = json.loads(response_line.decode())

        if "error" in response:
            msg = response["error"].get("message", "Unknown MCP error")
            raise MCPError(msg)

        result: dict[str, Any] = response.get("result", {})
        return result
