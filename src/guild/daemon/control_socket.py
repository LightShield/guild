"""Control socket for daemon communication (REQ-23.9, REQ-05.4a).

Provides a Unix domain socket interface for controlling a running daemon task,
injecting messages, and streaming agent responses to attached clients.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path  # noqa: TC003 — used at runtime
from typing import Any

from logger_python import get_logger

__all__ = ["ControlSocket"]

logger = get_logger(__name__)


class ControlSocket:
    """Unix domain socket server for daemon control and interactive attach."""

    def __init__(self, sock_path: Path) -> None:
        self._sock_path = sock_path
        self._server: asyncio.Server | None = None
        self._status: str = "idle"
        self._paused: bool = False
        self._shutdown_requested: bool = False
        self._message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers: list[asyncio.StreamWriter] = []

    @property
    def is_paused(self) -> bool:
        """Whether the daemon is currently paused."""
        return self._paused

    @property
    def shutdown_requested(self) -> bool:
        """Whether a shutdown has been requested via the kill command."""
        return self._shutdown_requested

    def set_status(self, status: str) -> None:
        """Set the current status string reported by the status command."""
        self._status = status

    async def start(self) -> None:
        """Start listening on the Unix domain socket."""
        # Use a pre-bound socket to work around the 104-byte AF_UNIX path
        # length limit on macOS when paths are long.
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock_str = str(self._sock_path)
        if len(sock_str.encode()) >= 104:
            # Bind using a relative path from the socket's parent directory.
            prev_cwd = os.getcwd()
            os.chdir(self._sock_path.parent)
            try:
                sock.bind(self._sock_path.name)
            finally:
                os.chdir(prev_cwd)
        else:
            sock.bind(sock_str)
        sock.setblocking(False)
        self._server = await asyncio.start_unix_server(self._handle_client, sock=sock)

    async def stop(self) -> None:
        """Stop the server and remove the socket file. Idempotent."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._sock_path.exists():
            self._sock_path.unlink()

    async def get_pending_message(self) -> str | None:
        """Pop the next pending message from the queue, or None if empty."""
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON message to all subscribed clients."""
        if not self._subscribers:
            return
        line = json.dumps(data).encode() + b"\n"
        disconnected: list[asyncio.StreamWriter] = []
        for writer in self._subscribers:
            try:
                writer.write(line)
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                disconnected.append(writer)
        for writer in disconnected:
            self._subscribers.remove(writer)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection."""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                response = self._process_line(line, writer)
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            if writer in self._subscribers:
                self._subscribers.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, ConnectionResetError):
                pass

    def _process_line(self, line: bytes, writer: asyncio.StreamWriter) -> dict[str, str]:
        """Parse a single line and return the response dict."""
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return {"error": "Invalid JSON"}

        msg_type: str = data.get("type", "")

        if msg_type == "command":
            return self._handle_command(data, writer)
        elif msg_type == "message":
            content: str = data.get("content", "")
            self._message_queue.put_nowait(content)
            return {"status": "delivered"}
        else:
            return {"error": f"Unknown type: {msg_type}"}

    def _handle_command(self, data: dict[str, Any], writer: asyncio.StreamWriter) -> dict[str, str]:
        """Dispatch a command action and return the response."""
        action: str = data.get("action", "")

        if action == "status":
            return {"status": self._status}
        elif action == "pause":
            self._paused = True
            return {"status": "paused"}
        elif action == "resume":
            self._paused = False
            return {"status": "running"}
        elif action == "kill":
            self._shutdown_requested = True
            return {"status": "shutting_down"}
        elif action == "subscribe":
            self._subscribers.append(writer)
            return {"status": "subscribed"}
        else:
            return {"error": f"Unknown action: {action}"}
