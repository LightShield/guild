"""Tests for daemon control socket (REQ-23.9) and interactive attach (REQ-05.4a).

Written BEFORE implementation (TDD red phase).
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.req("REQ-23.9")
class TestControlSocketLifecycle:
    """Control socket starts, accepts connections, and cleans up."""

    async def test_socket_file_created_on_start(self, tmp_path: Path) -> None:
        """Starting the socket creates the .sock file."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()
        assert sock_path.exists()
        await cs.stop()

    async def test_socket_file_removed_on_stop(self, tmp_path: Path) -> None:
        """Stopping the socket removes the .sock file."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()
        await cs.stop()
        assert not sock_path.exists()

    async def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        """Calling stop twice doesn't raise."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()
        await cs.stop()
        await cs.stop()  # Should not raise


@pytest.mark.req("REQ-23.9")
class TestControlSocketCommands:
    """Control socket handles command messages."""

    async def test_status_command_returns_running(self, tmp_path: Path) -> None:
        """A 'status' command returns current task state."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "status"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["status"] == "running"
        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_pause_command_sets_paused(self, tmp_path: Path) -> None:
        """A 'pause' command transitions to paused state."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "pause"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["status"] == "paused"
        assert cs.is_paused
        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_resume_command_clears_pause(self, tmp_path: Path) -> None:
        """A 'resume' command transitions back to running."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        cs.set_status("running")
        cs._paused = True
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "resume"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["status"] == "running"
        assert not cs.is_paused
        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_kill_command_requests_shutdown(self, tmp_path: Path) -> None:
        """A 'kill' command triggers shutdown."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "kill"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["status"] == "shutting_down"
        assert cs.shutdown_requested
        writer.close()
        await writer.wait_closed()
        await cs.stop()


@pytest.mark.req("REQ-05.4a")
class TestControlSocketMessageInjection:
    """Control socket injects user messages into the agent loop."""

    async def test_message_queued_for_agent(self, tmp_path: Path) -> None:
        """A 'message' type queues content for the agent loop to consume."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(
            json.dumps({"type": "message", "content": "focus on the auth module"}).encode() + b"\n"
        )
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["status"] == "delivered"

        # The message should be retrievable by the agent loop
        msg = await cs.get_pending_message()
        assert msg == "focus on the auth module"
        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_no_pending_message_returns_none(self, tmp_path: Path) -> None:
        """get_pending_message returns None when queue is empty."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        msg = await cs.get_pending_message()
        assert msg is None

    async def test_multiple_messages_queued_in_order(self, tmp_path: Path) -> None:
        """Multiple messages are delivered FIFO."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        for text in ["first", "second", "third"]:
            writer.write(json.dumps({"type": "message", "content": text}).encode() + b"\n")
            await writer.drain()
            await reader.readline()  # consume ack

        assert await cs.get_pending_message() == "first"
        assert await cs.get_pending_message() == "second"
        assert await cs.get_pending_message() == "third"
        assert await cs.get_pending_message() is None

        writer.close()
        await writer.wait_closed()
        await cs.stop()


@pytest.mark.req("REQ-05.4a")
class TestControlSocketResponseStreaming:
    """Agent responses stream back to attached clients."""

    async def test_broadcast_sends_to_connected_client(self, tmp_path: Path) -> None:
        """broadcast() sends a message to all connected clients."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        # Subscribe by sending a subscribe command
        writer.write(json.dumps({"type": "command", "action": "subscribe"}).encode() + b"\n")
        await writer.drain()
        ack = await reader.readline()
        assert json.loads(ack)["status"] == "subscribed"

        # Broadcast from the agent side
        await cs.broadcast({"type": "agent_message", "content": "working on auth module..."})

        # Client should receive it
        msg = await asyncio.wait_for(reader.readline(), timeout=2.0)
        data = json.loads(msg)
        assert data["type"] == "agent_message"
        assert data["content"] == "working on auth module..."

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_broadcast_with_no_subscribers_is_noop(self, tmp_path: Path) -> None:
        """broadcast() doesn't raise when no clients are connected."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()
        await cs.broadcast({"type": "agent_message", "content": "nobody listening"})
        await cs.stop()


@pytest.mark.req("REQ-23.9")
class TestControlSocketErrorHandling:
    """Socket handles malformed input gracefully."""

    async def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        """Malformed JSON gets an error response, connection stays open."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(b"not valid json\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert data["error"] is not None

        # Connection should still work after error
        writer.write(json.dumps({"type": "command", "action": "status"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert "status" in data

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    async def test_unknown_command_returns_error(self, tmp_path: Path) -> None:
        """Unknown action gets an error response."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "test.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "explode"}).encode() + b"\n")
        await writer.drain()
        response = await reader.readline()
        data = json.loads(response)
        assert "error" in data

        writer.close()
        await writer.wait_closed()
        await cs.stop()


@pytest.mark.req("REQ-23.9")
class TestSupervisorSocketIntegration:
    """Supervisor creates and manages control socket for each task."""

    async def test_supervisor_creates_socket(self, tmp_path: Path) -> None:
        """Supervisor creates a control socket on start_control_socket()."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="task-123")
        sup.write_pid_file()
        # After integration, supervisor should have a socket
        assert hasattr(sup, "control_socket")
        sock_path = tmp_path / "task-123.sock"
        await sup.start_control_socket()
        assert sock_path.exists()
        await sup.stop_control_socket()
        sup.remove_pid_file()

    async def test_supervisor_socket_kill_sets_shutdown(self, tmp_path: Path) -> None:
        """Kill command via socket triggers supervisor shutdown."""
        import json

        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="task-456")
        await sup.start_control_socket()
        sock_path = tmp_path / "task-456.sock"

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "kill"}).encode() + b"\n")
        await writer.drain()
        await reader.readline()
        writer.close()
        await writer.wait_closed()

        assert sup.shutdown_requested
        await sup.stop_control_socket()

    async def test_supervisor_socket_cleaned_on_stop(self, tmp_path: Path) -> None:
        """Socket file is removed when stop_control_socket() is called."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="task-789")
        await sup.start_control_socket()
        sock_path = tmp_path / "task-789.sock"
        assert sock_path.exists()
        await sup.stop_control_socket()
        assert not sock_path.exists()

    async def test_socket_path_property(self, tmp_path: Path) -> None:
        """socket_path property returns the expected path."""
        from guild.daemon.supervisor import DaemonSupervisor

        sup = DaemonSupervisor(run_dir=tmp_path, task_id="task-abc")
        assert sup.socket_path == tmp_path / "task-abc.sock"
