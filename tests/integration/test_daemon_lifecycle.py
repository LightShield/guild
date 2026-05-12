"""Integration tests: daemon lifecycle -- background task management.

Tests the full sequence: create task -> launch daemon -> check status ->
send control command -> verify cleanup.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from guild.daemon.control_socket import ControlSocket
from guild.daemon.supervisor import DaemonSupervisor
from guild.storage.sqlite import Storage

pytestmark = [pytest.mark.integration]


@pytest.fixture()
async def guild_env(tmp_path: Path) -> dict:
    """Set up a minimal guild environment with real storage."""
    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    run_dir = guild_dir / "run"
    run_dir.mkdir()
    db_path = guild_dir / "guild.db"

    store = Storage(db_path)
    await store.connect()
    yield {"guild_dir": guild_dir, "run_dir": run_dir, "store": store, "tmp_path": tmp_path}
    await store.close()


class TestDaemonControlSocketLifecycle:
    """Full lifecycle: start socket -> connect -> send commands -> stop."""

    async def test_full_command_sequence(self, guild_env: dict) -> None:
        """Start socket, send status/pause/resume/kill in sequence."""
        run_dir = guild_env["run_dir"]
        sock_path = run_dir / "lifecycle-test.sock"

        cs = ControlSocket(sock_path)
        cs.set_status("running")
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Status
        writer.write(json.dumps({"type": "command", "action": "status"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "running"

        # Pause
        writer.write(json.dumps({"type": "command", "action": "pause"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "paused"
        assert cs.is_paused

        # Resume
        writer.write(json.dumps({"type": "command", "action": "resume"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "running"
        assert not cs.is_paused

        # Kill
        writer.write(json.dumps({"type": "command", "action": "kill"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "shutting_down"
        assert cs.shutdown_requested

        writer.close()
        await writer.wait_closed()
        await cs.stop()
        assert not sock_path.exists()

    async def test_message_injection_and_retrieval(self, guild_env: dict) -> None:
        """Client sends messages, agent loop can retrieve them FIFO."""
        run_dir = guild_env["run_dir"]
        sock_path = run_dir / "msg-test.sock"

        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Send 3 messages
        for msg in ["focus on auth", "skip tests for now", "use async"]:
            writer.write(json.dumps({"type": "message", "content": msg}).encode() + b"\n")
            await writer.drain()
            ack = json.loads(await reader.readline())
            assert ack["status"] == "delivered"

        # Retrieve in order
        assert await cs.get_pending_message() == "focus on auth"
        assert await cs.get_pending_message() == "skip tests for now"
        assert await cs.get_pending_message() == "use async"
        assert await cs.get_pending_message() is None

        writer.close()
        await writer.wait_closed()
        await cs.stop()


class TestSupervisorWithSocket:
    """Supervisor manages both PID file and control socket."""

    async def test_supervisor_creates_and_cleans_up(self, guild_env: dict) -> None:
        """Supervisor creates PID + socket on start, removes both on stop."""
        run_dir = guild_env["run_dir"]
        sup = DaemonSupervisor(run_dir=run_dir, task_id="integ-task")

        sup.write_pid_file()
        await sup.start_control_socket()

        assert sup.pid_path.exists()
        assert sup.socket_path.exists()

        await sup.stop_control_socket()
        sup.remove_pid_file()

        assert not sup.pid_path.exists()
        assert not sup.socket_path.exists()
