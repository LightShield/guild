"""Tests for mcp/client.py — MCP client over stdio (REQ-04.6)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guild.mcp.client import MCPClient, MCPError, MCPServerConfig, MCPTool


def _make_fake_process(responses: list[dict]) -> MagicMock:
    """Create a fake asyncio.subprocess.Process with simulated stdio."""
    process = MagicMock()
    process.terminate = MagicMock()
    process.wait = AsyncMock()

    # Stdin mock
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()

    # Stdout mock — returns JSON lines for each response
    response_lines = [(json.dumps(r) + "\n").encode() for r in responses]
    process.stdout = MagicMock()
    process.stdout.readline = AsyncMock(side_effect=response_lines)

    # Stderr mock
    process.stderr = MagicMock()

    return process


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPClientConnect:
    """Tests for MCPClient.connect() — subprocess startup."""

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_connect_starts_subprocess(self, mock_exec: AsyncMock) -> None:
        """connect() launches the server command as a subprocess."""
        fake_proc = _make_fake_process([])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(
            name="test-server",
            command="npx",
            args=["@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        client = MCPClient(config)
        await client.connect()

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[0][0] == "npx"
        assert "@modelcontextprotocol/server-filesystem" in call_args[0]


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPClientDisconnect:
    """Tests for MCPClient.disconnect() — subprocess termination."""

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_disconnect_terminates_subprocess(self, mock_exec: AsyncMock) -> None:
        """disconnect() terminates the server subprocess and waits."""
        fake_proc = _make_fake_process([])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="test", command="echo", args=[])
        client = MCPClient(config)
        await client.connect()
        await client.disconnect()

        fake_proc.terminate.assert_called_once()
        fake_proc.wait.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPClientListTools:
    """Tests for MCPClient.list_tools() — fetching tool definitions."""

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_list_tools_returns_tool_objects(self, mock_exec: AsyncMock) -> None:
        """list_tools() returns MCPTool objects from server response."""
        tools_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file from disk",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                    {
                        "name": "write_file",
                        "description": "Write to a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                        },
                    },
                ]
            },
        }
        fake_proc = _make_fake_process([tools_response])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="fs-server", command="npx", args=["server"])
        client = MCPClient(config)
        await client.connect()

        tools = await client.list_tools()

        assert len(tools) == 2
        assert isinstance(tools[0], MCPTool)
        assert tools[0].name == "read_file"
        assert tools[0].description == "Read a file from disk"
        assert tools[0].server_name == "fs-server"
        assert tools[1].name == "write_file"


@pytest.mark.unit
@pytest.mark.req("REQ-04.6")
class TestMCPClientCallTool:
    """Tests for MCPClient.call_tool() — invoking tools on the server."""

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_call_tool_sends_jsonrpc_request(self, mock_exec: AsyncMock) -> None:
        """call_tool() sends a properly formatted JSON-RPC request."""
        call_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "file data"}]},
        }
        fake_proc = _make_fake_process([call_response])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="test", command="echo", args=[])
        client = MCPClient(config)
        await client.connect()

        await client.call_tool("read_file", {"path": "/tmp/test.txt"})

        # Verify the request written to stdin
        written_data = fake_proc.stdin.write.call_args[0][0]
        request = json.loads(written_data.decode())
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "tools/call"
        assert request["params"]["name"] == "read_file"
        assert request["params"]["arguments"] == {"path": "/tmp/test.txt"}

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_call_tool_returns_result(self, mock_exec: AsyncMock) -> None:
        """call_tool() returns the result from the server response."""
        call_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "hello world"}]},
        }
        fake_proc = _make_fake_process([call_response])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="test", command="echo", args=[])
        client = MCPClient(config)
        await client.connect()

        result = await client.call_tool("read_file", {"path": "/tmp/x"})

        assert result == {"content": [{"type": "text", "text": "hello world"}]}

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_error_response_raises_mcp_error(self, mock_exec: AsyncMock) -> None:
        """An error response from the server raises MCPError."""
        error_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        fake_proc = _make_fake_process([error_response])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="test", command="echo", args=[])
        client = MCPClient(config)
        await client.connect()

        with pytest.raises(MCPError, match="Method not found"):
            await client.call_tool("nonexistent", {})

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_request_id_increments(self, mock_exec: AsyncMock) -> None:
        """Each request gets a unique incrementing ID."""
        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            },
        ]
        fake_proc = _make_fake_process(responses)
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="test", command="echo", args=[])
        client = MCPClient(config)
        await client.connect()

        await client.list_tools()
        await client.call_tool("test_tool", {})

        # Check both requests had incrementing IDs
        calls = fake_proc.stdin.write.call_args_list
        req1 = json.loads(calls[0][0][0].decode())
        req2 = json.loads(calls[1][0][0].decode())
        assert req1["id"] == 1
        assert req2["id"] == 2


@pytest.mark.unit
@pytest.mark.req("REQ-04.3")
class TestMCPClientAsyncContextManager:
    """Tests for MCPClient.__aenter__/__aexit__ — async context manager."""

    @patch("guild.mcp.client.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_async_with_calls_connect_and_disconnect(
        self, mock_exec: AsyncMock
    ) -> None:
        """Using `async with MCPClient(...)` calls connect on enter and disconnect on exit."""
        fake_proc = _make_fake_process([])
        mock_exec.return_value = fake_proc

        config = MCPServerConfig(name="ctx-server", command="echo", args=[])

        with (
            patch.object(MCPClient, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(MCPClient, "disconnect", new_callable=AsyncMock) as mock_disconnect,
        ):
            async with MCPClient(config) as client:
                assert isinstance(client, MCPClient)
                mock_connect.assert_awaited_once()
                mock_disconnect.assert_not_awaited()

            mock_disconnect.assert_awaited_once()


# ======================================================================
# MCP Client edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.3")
class TestMCPClientEdgeCases:
    """Cover MCP client edge cases."""

    async def test_disconnect_when_not_connected(self) -> None:
        """disconnect() is a no-op when not connected."""
        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        # Should not raise
        await client.disconnect()

    async def test_send_request_not_connected_raises(self) -> None:
        """_send_request raises MCPError when not connected."""
        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        with pytest.raises(MCPError, match="Not connected"):
            await client._send_request("test/method", {})

    def test_config_property(self) -> None:
        """config property returns the server config."""
        config = MCPServerConfig(name="my-server", command="node", args=["mcp.js"])
        client = MCPClient(config)
        assert client.config.name == "my-server"


# ======================================================================
# MCP Client protocol edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.3")
class TestMCPClientProtocol:
    """Test MCP client protocol edge cases."""

    async def test_send_request_stdout_none_raises(self) -> None:
        """_send_request raises MCPError if stdout is None."""
        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        # Simulate connected but with stdout=None
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = None
        client._process = mock_proc

        with pytest.raises(MCPError, match="stdout"):
            await client._send_request("test", {})

    async def test_send_request_empty_response_raises(self) -> None:
        """_send_request raises MCPError when server closes connection."""
        config = MCPServerConfig(name="test", command="echo")
        client = MCPClient(config)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")
        client._process = mock_proc

        with pytest.raises(MCPError, match="closed connection"):
            await client._send_request("test", {})
