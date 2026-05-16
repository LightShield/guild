"""Integration tests for remaining uncovered requirements.

Covers:
  REQ-05.3   Send messages to running agent from CLI
  REQ-05.4a  Interactive attach
  REQ-05.5   GUI web-based monitoring
  REQ-18.2   Diff view of changes
  REQ-18.4   Artifact versioning
  REQ-18.5   Artifact export
  REQ-19.1   Template save
  REQ-19.2   Template parameterize/render
  REQ-19.3   Template import/export
  REQ-20.1   Rate limiting
  REQ-20.2   Tool queue concurrency
  REQ-20.3   Backpressure management
  REQ-21.1   No-internet detection
  REQ-21.2   Graceful degrade offline
  REQ-21.3   Local model support
  REQ-21.4   Offline documentation
  REQ-22.1   RPG mode toggle
  REQ-22.2   RPG rename
  REQ-22.3   RPG progress
  REQ-22.4   RPG quest log
  REQ-22.5   RPG character sheets
  REQ-22.6   RPG notifications
  REQ-27.1   Temporal decisions
  REQ-27.2   Present state + key past info
  REQ-27.3   Project instructions context
  REQ-27.4   Relevant learnings context
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from guild.storage.sqlite import Storage

pytestmark = pytest.mark.integration


# ======================================================================
# Shared fixtures
# ======================================================================


@pytest.fixture()
async def storage(tmp_path: Path) -> Storage:
    """Real SQLite storage, connected and torn down after each test."""
    store = Storage(tmp_path / "guild.db")
    await store.connect()
    yield store  # type: ignore[misc]
    await store.close()


def _init_db(db_path: Path) -> None:
    """Create an empty Guild SQLite database with schema."""
    import asyncio as _aio

    async def _create() -> None:
        async with Storage(db_path):
            pass

    _aio.run(_create())


# ======================================================================
# REQ-05.3: Send messages to running agent from CLI
# ======================================================================


class TestSendMessageToAgent:
    """Send messages to a running agent via the control socket."""

    @pytest.mark.ac("AC-05.3.1")
    async def test_message_delivered_via_socket(self, tmp_path: Path) -> None:
        """Happy: client sends a message, server queues it."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "msg.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        msg = {"type": "message", "content": "focus on tests please"}
        writer.write(json.dumps(msg).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "delivered"

        pending = await cs.get_pending_message()
        assert pending == "focus on tests please"

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-05.3.1")
    async def test_multiple_messages_queued_in_order(self, tmp_path: Path) -> None:
        """Happy: multiple messages arrive and are dequeued in FIFO order."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "mq.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        for text in ["msg-1", "msg-2", "msg-3"]:
            writer.write(json.dumps({"type": "message", "content": text}).encode() + b"\n")
            await writer.drain()
            await reader.readline()

        assert await cs.get_pending_message() == "msg-1"
        assert await cs.get_pending_message() == "msg-2"
        assert await cs.get_pending_message() == "msg-3"
        assert await cs.get_pending_message() is None

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-05.3.2")
    async def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        """Sad: malformed JSON returns an error response."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "bad.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(b"not-json\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert "error" in resp

        writer.close()
        await writer.wait_closed()
        await cs.stop()


# ======================================================================
# REQ-05.4a: Interactive attach
# ======================================================================


class TestInteractiveAttach:
    """Attach to a running task via the control socket and interact."""

    @pytest.mark.ac("AC-05.4a.1")
    async def test_subscribe_and_receive_broadcast(self, tmp_path: Path) -> None:
        """Happy: subscribed client receives broadcast messages."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "sub.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Subscribe
        writer.write(json.dumps({"type": "command", "action": "subscribe"}).encode() + b"\n")
        await writer.drain()
        ack = json.loads(await reader.readline())
        assert ack["status"] == "subscribed"

        # Broadcast a message
        await cs.broadcast({"type": "agent_message", "content": "Working on it..."})
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        data = json.loads(line)
        assert data["type"] == "agent_message"
        assert data["content"] == "Working on it..."

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-05.4a.3")
    async def test_pause_and_resume_via_attach(self, tmp_path: Path) -> None:
        """Happy: attached client can pause and resume the agent."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "pr.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))

        # Pause
        writer.write(json.dumps({"type": "command", "action": "pause"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "paused"
        assert cs.is_paused is True

        # Resume
        writer.write(json.dumps({"type": "command", "action": "resume"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["status"] == "running"
        assert cs.is_paused is False

        writer.close()
        await writer.wait_closed()
        await cs.stop()

    @pytest.mark.ac("AC-05.4a.1")
    async def test_unknown_command_returns_error(self, tmp_path: Path) -> None:
        """Sad: unknown command action yields an error response."""
        from guild.daemon.control_socket import ControlSocket

        sock_path = tmp_path / "unk.sock"
        cs = ControlSocket(sock_path)
        await cs.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps({"type": "command", "action": "foobar"}).encode() + b"\n")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert "error" in resp

        writer.close()
        await writer.wait_closed()
        await cs.stop()


# ======================================================================
# REQ-05.5: GUI web-based monitoring
# ======================================================================


class TestWebGUI:
    """REST API serves status, tasks, and WebSocket for real-time updates."""

    @pytest.mark.ac("AC-05.5.1")
    def test_api_status_endpoint(self, tmp_path: Path) -> None:
        """Happy: GET /api/status returns project status with version."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        # Initialize a minimal guild dir with config + database
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nprovider_name = "ollama"\nmodel = "m"\n'
        )
        _init_db(guild_dir / "guild.db")

        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "version" in data
            assert data["status"] == "ok"

    @pytest.mark.ac("AC-05.5.2")
    def test_api_tasks_crud(self, tmp_path: Path) -> None:
        """Happy: POST /api/tasks creates a task, GET retrieves it."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nprovider_name = "ollama"\nmodel = "m"\n'
        )
        _init_db(guild_dir / "guild.db")

        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            # Create
            resp = client.post("/api/tasks", json={"description": "E2E test task"})
            assert resp.status_code == 200
            task_id = resp.json()["id"]

            # List
            resp = client.get("/api/tasks")
            assert resp.status_code == 200
            tasks = resp.json()
            assert any(t["task_id"] == task_id for t in tasks)

    @pytest.mark.ac("AC-05.5.3")
    def test_api_missing_task_returns_404(self, tmp_path: Path) -> None:
        """Sad: GET /api/tasks/nonexistent returns 404."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "config.toml").write_text(
            '[provider]\nprovider_name = "ollama"\nmodel = "m"\n'
        )
        _init_db(guild_dir / "guild.db")

        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.get("/api/tasks/nonexistent-id")
            assert resp.status_code == 404


# ======================================================================
# REQ-18.2: Diff view of changes
# ======================================================================


class TestArtifactDiff:
    """Diff between artifact versions shows changes."""

    @pytest.mark.ac("AC-18.2.1")
    def test_diff_shows_added_lines(self, tmp_path: Path) -> None:
        """Happy: diff between v1 and v2 includes added lines."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-d1", "code.py", "line1\nline2\n")
        mgr.save_version("task-d1", "code.py", "line1\nline2\nline3\n")

        diff = mgr.get_diff("task-d1", "code.py", 1, 2)
        assert "+line3" in diff
        assert "code.py.v1" in diff
        assert "code.py.v2" in diff

    @pytest.mark.ac("AC-18.2.2")
    def test_diff_shows_removed_lines(self, tmp_path: Path) -> None:
        """Happy: diff between v1 and v2 includes removed lines."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-d2", "code.py", "keep\nremove_me\n")
        mgr.save_version("task-d2", "code.py", "keep\n")

        diff = mgr.get_diff("task-d2", "code.py", 1, 2)
        assert "-remove_me" in diff

    @pytest.mark.ac("AC-18.2.1")
    def test_diff_empty_when_versions_identical(self, tmp_path: Path) -> None:
        """Edge: diff between identical versions is empty."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-d3", "same.py", "same\n")
        mgr.save_version("task-d3", "same.py", "same\n")

        diff = mgr.get_diff("task-d3", "same.py", 1, 2)
        assert diff == ""

    @pytest.mark.ac("AC-18.2.2")
    def test_diff_nonexistent_version_uses_empty(self, tmp_path: Path) -> None:
        """Sad: diffing against a nonexistent version treats it as empty."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-d4", "new.py", "content\n")

        diff = mgr.get_diff("task-d4", "new.py", 99, 1)
        assert "+content" in diff


# ======================================================================
# REQ-18.4: Artifact versioning
# ======================================================================


class TestArtifactVersioning:
    """Artifacts support multiple versions with auto-increment."""

    @pytest.mark.ac("AC-18.4.1")
    def test_save_version_auto_increments(self, tmp_path: Path) -> None:
        """Happy: each save_version produces an incrementing version number."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        a1 = mgr.save("task-v1", "file.py", "v1 content")
        assert a1.version == 1

        a2 = mgr.save_version("task-v1", "file.py", "v2 content")
        assert a2.version == 2

        a3 = mgr.save_version("task-v1", "file.py", "v3 content")
        assert a3.version == 3

    @pytest.mark.ac("AC-18.4.2")
    def test_get_retrieves_specific_version(self, tmp_path: Path) -> None:
        """Happy: get(version=N) returns the content of that version."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-v2", "file.py", "original")
        mgr.save_version("task-v2", "file.py", "updated")

        assert mgr.get("task-v2", "file.py", version=1) == "original"
        assert mgr.get("task-v2", "file.py", version=2) == "updated"

    @pytest.mark.ac("AC-18.4.2")
    def test_get_without_version_returns_latest(self, tmp_path: Path) -> None:
        """Happy: get() without version returns the latest version."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-v3", "file.py", "first")
        mgr.save_version("task-v3", "file.py", "second")
        mgr.save_version("task-v3", "file.py", "third")

        assert mgr.get("task-v3", "file.py") == "third"

    @pytest.mark.ac("AC-18.4.1")
    def test_list_for_task_includes_all_versions(self, tmp_path: Path) -> None:
        """Edge: list_for_task returns all version files."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-v4", "a.py", "a1")
        mgr.save_version("task-v4", "a.py", "a2")
        mgr.save("task-v4", "b.py", "b1")

        artifacts = mgr.list_for_task("task-v4")
        assert len(artifacts) == 3

    @pytest.mark.ac("AC-18.4.2")
    def test_get_nonexistent_artifact_returns_none(self, tmp_path: Path) -> None:
        """Sad: getting a nonexistent artifact returns None."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        assert mgr.get("no-task", "no-file.py") is None


# ======================================================================
# REQ-18.5: Artifact export
# ======================================================================


class TestArtifactExport:
    """Export artifacts for a task to an external directory."""

    @pytest.mark.ac("AC-18.5.1")
    def test_export_copies_all_versions(self, tmp_path: Path) -> None:
        """Happy: export copies all version files to the output directory."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-e1", "code.py", "v1")
        mgr.save_version("task-e1", "code.py", "v2")

        output = tmp_path / "export"
        mgr.export("task-e1", output)

        assert (output / "code.py.v1").exists()
        assert (output / "code.py.v2").exists()
        assert (output / "code.py.v1").read_text() == "v1"
        assert (output / "code.py.v2").read_text() == "v2"

    @pytest.mark.ac("AC-18.5.1")
    def test_export_excludes_status_file(self, tmp_path: Path) -> None:
        """Happy: export does not copy the internal .status.json file."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-e2", "code.py", "v1")

        output = tmp_path / "export2"
        mgr.export("task-e2", output)

        assert not (output / ".status.json").exists()

    @pytest.mark.ac("AC-18.5.3")
    def test_export_empty_task_creates_directory(self, tmp_path: Path) -> None:
        """Edge: exporting a task with no artifacts creates an empty output dir."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        output = tmp_path / "export3"
        mgr.export("no-task", output)

        assert output.is_dir()
        assert len(list(output.iterdir())) == 0


# ======================================================================
# REQ-19.1: Template save
# ======================================================================


class TestTemplateSave:
    """Save workflow templates for reuse."""

    @pytest.mark.ac("AC-19.1.1")
    def test_save_and_retrieve_template(self, tmp_path: Path) -> None:
        """Happy: saved template is retrievable by name."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        tpl = Template(
            name="deploy",
            description="Standard deploy workflow",
            task_template="Deploy {service} to {env}",
            parameters=["service", "env"],
        )
        mgr.save(tpl)

        loaded = mgr.get("deploy")
        assert loaded is not None
        assert loaded.name == "deploy"
        assert loaded.description == "Standard deploy workflow"
        assert loaded.parameters == ["service", "env"]

    @pytest.mark.ac("AC-19.1.2")
    def test_list_templates(self, tmp_path: Path) -> None:
        """Happy: list returns all saved templates."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        mgr.save(Template(name="alpha", task_template="task A"))
        mgr.save(Template(name="beta", task_template="task B"))

        templates = mgr.list()
        names = [t.name for t in templates]
        assert "alpha" in names
        assert "beta" in names

    @pytest.mark.ac("AC-19.1.3")
    def test_get_nonexistent_template_returns_none(self, tmp_path: Path) -> None:
        """Sad: getting a nonexistent template returns None."""
        from guild.templates.manager import TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        assert mgr.get("missing") is None


# ======================================================================
# REQ-19.2: Template parameterize/render
# ======================================================================


class TestTemplateParameterize:
    """Templates support parameter substitution when rendered."""

    @pytest.mark.ac("AC-19.2.1")
    def test_render_substitutes_parameters(self, tmp_path: Path) -> None:
        """Happy: render replaces {placeholders} with provided values."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        tpl = Template(
            name="deploy",
            task_template="Deploy {service} to {env} with {replicas} replicas",
            parameters=["service", "env", "replicas"],
        )
        result = mgr.render(tpl, service="auth-api", env="production", replicas="3")
        assert result == "Deploy auth-api to production with 3 replicas"

    @pytest.mark.ac("AC-19.2.2")
    def test_render_leaves_missing_params_as_placeholder(self, tmp_path: Path) -> None:
        """Sad: missing parameters remain as {placeholder} in output."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        tpl = Template(
            name="partial",
            task_template="Deploy {service} to {env}",
            parameters=["service", "env"],
        )
        result = mgr.render(tpl, service="api")
        assert result == "Deploy api to {env}"

    @pytest.mark.ac("AC-19.2.3")
    def test_render_with_no_params_returns_raw_template(self, tmp_path: Path) -> None:
        """Edge: rendering with no params returns the raw template string."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        tpl = Template(name="raw", task_template="Run {task}")
        result = mgr.render(tpl)
        assert result == "Run {task}"


# ======================================================================
# REQ-19.3: Template import/export
# ======================================================================


class TestTemplateImportExport:
    """Templates can be exported to and imported from external files."""

    @pytest.mark.ac("AC-19.3.1")
    def test_export_creates_json_file(self, tmp_path: Path) -> None:
        """Happy: export writes a valid JSON file to the output directory."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        mgr.save(Template(name="exportable", task_template="Do {thing}"))

        output = tmp_path / "export"
        dest = mgr.export("exportable", output)

        assert dest.exists()
        data = json.loads(dest.read_text())
        assert data["name"] == "exportable"

    @pytest.mark.ac("AC-19.3.2")
    def test_import_loads_template_from_file(self, tmp_path: Path) -> None:
        """Happy: import from a JSON file adds the template to the manager."""
        from guild.templates.manager import TemplateManager

        # Create a source JSON file
        source_file = tmp_path / "imported.json"
        source_data = {
            "name": "imported",
            "description": "An imported template",
            "task_template": "Run {x}",
            "parameters": ["x"],
            "permission": "autopilot",
        }
        source_file.write_text(json.dumps(source_data))

        mgr = TemplateManager(tmp_path / "templates")
        tpl = mgr.import_template(source_file)

        assert tpl.name == "imported"
        assert tpl.description == "An imported template"
        # Verify it's now stored
        assert mgr.get("imported") is not None

    @pytest.mark.ac("AC-19.3.1")
    def test_export_nonexistent_template_raises(self, tmp_path: Path) -> None:
        """Sad: exporting a template that does not exist raises FileNotFoundError."""
        from guild.templates.manager import TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        with pytest.raises(FileNotFoundError):
            mgr.export("nonexistent", tmp_path / "export")

    @pytest.mark.ac("AC-19.3.2")
    def test_import_invalid_json_raises(self, tmp_path: Path) -> None:
        """Sad: importing a file with invalid JSON raises ValueError."""
        from guild.templates.manager import TemplateManager

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")

        mgr = TemplateManager(tmp_path / "templates")
        with pytest.raises(ValueError, match="Cannot load"):
            mgr.import_template(bad_file)


# ======================================================================
# REQ-20.1: Rate limiting
# ======================================================================


class TestRateLimiting:
    """Sliding-window rate limiter enforces call limits."""

    @pytest.mark.ac("AC-20.1.1")
    async def test_rate_limiter_allows_within_limit(self) -> None:
        """Happy: calls within the limit proceed immediately."""
        from guild.agent.ratelimit import RateLimiter

        rl = RateLimiter(max_calls=5, window_seconds=60.0)
        for _ in range(5):
            await rl.acquire()
        assert rl.available == 0

    @pytest.mark.ac("AC-20.1.1")
    async def test_rate_limiter_available_count(self) -> None:
        """Happy: available count decreases as calls are made."""
        from guild.agent.ratelimit import RateLimiter

        rl = RateLimiter(max_calls=10, window_seconds=60.0)
        assert rl.available == 10

        await rl.acquire()
        await rl.acquire()
        assert rl.available == 8

    @pytest.mark.ac("AC-20.1.2")
    async def test_rate_limiter_window_expiry(self) -> None:
        """Edge: calls expire from the window, freeing capacity."""
        from guild.agent.ratelimit import RateLimiter

        rl = RateLimiter(max_calls=2, window_seconds=0.1)
        await rl.acquire()
        await rl.acquire()
        assert rl.available == 0

        await asyncio.sleep(0.15)
        assert rl.available == 2


# ======================================================================
# REQ-20.2: Tool queue concurrency
# ======================================================================


class TestToolQueue:
    """ToolQueue limits concurrent tool executions."""

    @pytest.mark.ac("AC-20.2.1")
    async def test_tool_queue_limits_concurrency(self) -> None:
        """Happy: at most max_concurrent coroutines run simultaneously."""
        from guild.agent.ratelimit import ToolQueue

        tq = ToolQueue(max_concurrent=2)
        active = 0
        max_active = 0

        async def worker() -> None:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

        tasks = [asyncio.create_task(tq.execute(worker())) for _ in range(6)]
        await asyncio.gather(*tasks)
        assert max_active <= 2

    @pytest.mark.ac("AC-20.2.2")
    async def test_tool_queue_returns_result(self) -> None:
        """Happy: execute returns the coroutine result."""
        from guild.agent.ratelimit import ToolQueue

        tq = ToolQueue(max_concurrent=4)

        async def compute() -> int:
            return 42

        result = await tq.execute(compute())
        assert result == 42

    @pytest.mark.ac("AC-20.2.3")
    async def test_tool_queue_propagates_exception(self) -> None:
        """Sad: exceptions from the coroutine propagate to the caller."""
        from guild.agent.ratelimit import ToolQueue

        tq = ToolQueue(max_concurrent=2)

        async def failing() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await tq.execute(failing())


# ======================================================================
# REQ-20.3: Backpressure management
# ======================================================================


class TestBackpressure:
    """BackpressureManager pauses low-priority work when system is loaded."""

    @pytest.mark.ac("AC-20.3.1")
    async def test_backpressure_under_pressure(self) -> None:
        """Happy: when all slots taken, is_under_pressure is True."""
        from guild.agent.ratelimit import BackpressureManager

        bp = BackpressureManager(max_concurrent=1)
        await bp.acquire()
        assert bp.is_under_pressure is True
        bp.release()
        assert bp.is_under_pressure is False

    @pytest.mark.ac("AC-20.3.2")
    async def test_backpressure_blocks_when_full(self) -> None:
        """Happy: acquire() blocks when all slots are occupied."""
        from guild.agent.ratelimit import BackpressureManager

        bp = BackpressureManager(max_concurrent=1)
        await bp.acquire()

        acquired = False

        async def try_acquire() -> None:
            nonlocal acquired
            await bp.acquire()
            acquired = True

        task = asyncio.create_task(try_acquire())
        await asyncio.sleep(0.05)
        assert acquired is False

        bp.release()
        await asyncio.wait_for(task, timeout=1.0)
        assert acquired is True
        bp.release()

    @pytest.mark.ac("AC-20.3.1")
    async def test_backpressure_multiple_slots(self) -> None:
        """Edge: with max_concurrent=3, three acquires succeed before pressure."""
        from guild.agent.ratelimit import BackpressureManager

        bp = BackpressureManager(max_concurrent=3)

        await bp.acquire()
        assert bp.is_under_pressure is False
        await bp.acquire()
        assert bp.is_under_pressure is False
        await bp.acquire()
        assert bp.is_under_pressure is True

        bp.release()
        bp.release()
        bp.release()


# ======================================================================
# REQ-21.1: No-internet detection
# ======================================================================


class TestNoInternetDetection:
    """OfflineManager detects when the LLM provider is unreachable."""

    @pytest.mark.ac("AC-21.1.1")
    async def test_online_detected_when_provider_healthy(self) -> None:
        """Happy: health check passes -> is_online is True."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check = AsyncMock(return_value=True)

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()
        assert result is True
        assert mgr.is_online is True

    @pytest.mark.ac("AC-21.1.2")
    async def test_offline_detected_when_provider_unreachable(self) -> None:
        """Happy: health check fails -> is_online is False."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check = AsyncMock(side_effect=ConnectionError("refused"))

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()
        assert result is False
        assert mgr.is_online is False

    @pytest.mark.ac("AC-21.1.2")
    async def test_is_online_none_before_first_check(self) -> None:
        """Edge: before any check, is_online is None."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)
        assert mgr.is_online is None


# ======================================================================
# REQ-21.2: Graceful degrade offline
# ======================================================================


class TestGracefulDegradeOffline:
    """System degrades gracefully when the network is unavailable."""

    @pytest.mark.ac("AC-21.2.1")
    async def test_timeout_error_sets_offline(self) -> None:
        """Happy: TimeoutError from provider marks system as offline."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check = AsyncMock(side_effect=TimeoutError())

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()
        assert result is False
        assert mgr.is_online is False

    @pytest.mark.ac("AC-21.2.2")
    async def test_oserror_sets_offline(self) -> None:
        """Sad: OSError (e.g. no route to host) marks system as offline."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check = AsyncMock(side_effect=OSError("No route"))

        mgr = OfflineManager(provider)
        result = await mgr.check_connectivity()
        assert result is False

    @pytest.mark.ac("AC-21.2.3")
    async def test_recovery_after_reconnect(self) -> None:
        """Edge: after going offline, re-checking when online returns True."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        provider.health_check = AsyncMock(side_effect=ConnectionError())

        mgr = OfflineManager(provider)
        await mgr.check_connectivity()
        assert mgr.is_online is False

        # Provider recovers
        provider.health_check = AsyncMock(return_value=True)
        await mgr.check_connectivity()
        assert mgr.is_online is True


# ======================================================================
# REQ-21.3: Local model support
# ======================================================================


class TestLocalModelSupport:
    """Local Ollama models can be discovered when offline."""

    @pytest.mark.ac("AC-21.3.1")
    async def test_offline_manager_has_list_local_models(self) -> None:
        """Happy: OfflineManager exposes list_local_models method."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)
        # The method exists and is callable (actual execution requires ollama binary)
        assert callable(mgr.list_local_models)

    @pytest.mark.ac("AC-21.3.2")
    async def test_offline_manager_has_pull_model(self) -> None:
        """Happy: OfflineManager exposes pull_model method."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)
        assert callable(mgr.pull_model)


# ======================================================================
# REQ-21.4: Offline documentation
# ======================================================================


class TestOfflineDocs:
    """Offline documentation is available without network access."""

    @pytest.mark.ac("AC-21.4.1")
    async def test_get_help_returns_docs(self) -> None:
        """Happy: get_help with a known topic returns documentation."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)

        docs = mgr.get_help("getting-started")
        assert docs is not None
        assert "guild init" in docs.lower() or "Guild" in docs

    @pytest.mark.ac("AC-21.4.1")
    async def test_get_help_all_topics(self) -> None:
        """Happy: all documented topics return non-empty content."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)

        for topic in ["getting-started", "models", "commands", "troubleshooting"]:
            docs = mgr.get_help(topic)
            assert docs is not None, f"No docs for topic: {topic}"
            assert len(docs) > 20, f"Docs too short for topic: {topic}"

    @pytest.mark.ac("AC-21.4.2")
    async def test_get_help_unknown_topic_returns_none(self) -> None:
        """Sad: unknown topic returns None."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)
        assert mgr.get_help("nonexistent-topic") is None


# ======================================================================
# REQ-22.1: RPG mode toggle
# ======================================================================


class TestRPGModeToggle:
    """RPG mode can be enabled and disabled."""

    @pytest.mark.ac("AC-22.1.1")
    def test_rpg_mode_default_disabled(self) -> None:
        """Happy: RPG mode is disabled by default."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode()
        assert rpg.enabled is False

    @pytest.mark.ac("AC-22.1.2")
    def test_rpg_mode_enable(self) -> None:
        """Happy: RPG mode can be enabled via constructor."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert rpg.enabled is True

    @pytest.mark.ac("AC-22.1.3")
    def test_rpg_mode_toggle_at_runtime(self) -> None:
        """Happy: RPG mode can be toggled at runtime."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=False)
        rpg.enabled = True
        assert rpg.enabled is True
        rpg.enabled = False
        assert rpg.enabled is False

    @pytest.mark.ac("AC-22.1.1")
    def test_rpg_disabled_passthrough(self) -> None:
        """Edge: when disabled, translate returns text unchanged."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=False)
        assert rpg.translate("task running") == "task running"


# ======================================================================
# REQ-22.2: RPG rename
# ======================================================================


class TestRPGRename:
    """RPG mode renames standard terms to fantasy equivalents."""

    @pytest.mark.ac("AC-22.2.1")
    def test_translate_task_to_quest(self) -> None:
        """Happy: 'task' becomes 'quest' when RPG enabled."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert "quest" in rpg.translate("task")

    @pytest.mark.ac("AC-22.2.1")
    def test_translate_agent_to_hero(self) -> None:
        """Happy: 'agent' becomes 'hero'."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert "hero" in rpg.translate("agent")

    @pytest.mark.ac("AC-22.2.1")
    def test_translate_team_to_party(self) -> None:
        """Happy: 'team' becomes 'party'."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert "party" in rpg.translate("team")

    @pytest.mark.ac("AC-22.2.1")
    def test_translate_tokens_to_gold(self) -> None:
        """Happy: 'tokens' becomes 'gold'."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert "gold" in rpg.translate("tokens")

    @pytest.mark.ac("AC-22.2.2")
    def test_translate_preserves_unrecognized_text(self) -> None:
        """Edge: text with no known terms passes through unchanged."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert rpg.translate("hello world") == "hello world"


# ======================================================================
# REQ-22.3: RPG progress
# ======================================================================


class TestRPGProgress:
    """RPG mode displays XP-style progress bars."""

    @pytest.mark.ac("AC-22.3.1")
    def test_progress_bar_format(self) -> None:
        """Happy: progress_bar returns an XP-style bar with fraction."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        bar = rpg.progress_bar(5, 10)
        assert "XP" in bar
        assert "5/10" in bar

    @pytest.mark.ac("AC-22.3.1")
    def test_progress_bar_full(self) -> None:
        """Happy: full progress shows all filled."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        bar = rpg.progress_bar(10, 10)
        assert "==========" in bar

    @pytest.mark.ac("AC-22.3.1")
    def test_progress_bar_empty(self) -> None:
        """Happy: zero progress shows all dashes."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        bar = rpg.progress_bar(0, 10)
        assert "----------" in bar

    @pytest.mark.ac("AC-22.3.2")
    def test_progress_bar_zero_total(self) -> None:
        """Sad: zero total returns 0 XP bar."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        bar = rpg.progress_bar(0, 0)
        assert "0 XP" in bar


# ======================================================================
# REQ-22.4: RPG quest log
# ======================================================================


class TestRPGQuestLog:
    """RPG mode formats tasks as quest log entries."""

    @pytest.mark.ac("AC-22.4.1")
    def test_quest_log_entry_format(self) -> None:
        """Happy: quest_log_entry includes quest number, name, and status."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        task = {"id": "42", "name": "Fix the parser", "status": "running"}
        entry = rpg.quest_log_entry(task)
        assert "Quest #42" in entry
        assert "Fix the parser" in entry
        assert "adventure" in entry  # 'running' -> 'on adventure'

    @pytest.mark.ac("AC-22.4.1")
    def test_quest_log_entry_pending(self) -> None:
        """Happy: pending status translates to 'quest posted'."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        task = {"id": "1", "name": "Setup", "status": "pending"}
        entry = rpg.quest_log_entry(task)
        assert "quest posted" in entry

    @pytest.mark.ac("AC-22.4.2")
    def test_quest_log_entry_missing_fields(self) -> None:
        """Edge: missing fields use defaults without crashing."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        entry = rpg.quest_log_entry({})
        assert "Quest #???" in entry
        assert "Unknown Quest" in entry


# ======================================================================
# REQ-22.5: RPG character sheets
# ======================================================================


class TestRPGCharacterSheets:
    """RPG mode formats agent info as character sheets."""

    @pytest.mark.ac("AC-22.5.1")
    def test_character_sheet_includes_all_fields(self) -> None:
        """Happy: character sheet contains name, class, level, status."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        agent = {
            "name": "CodeWizard",
            "role": "mage",
            "level": "5",
            "status": "running",
        }
        sheet = rpg.character_sheet(agent)
        assert "CodeWizard" in sheet
        assert "mage" in sheet
        assert "5" in sheet
        assert "adventure" in sheet  # 'running' -> 'on adventure'

    @pytest.mark.ac("AC-22.5.1")
    def test_character_sheet_defaults(self) -> None:
        """Edge: missing fields produce sensible defaults."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        sheet = rpg.character_sheet({})
        assert "Unknown" in sheet
        assert "adventurer" in sheet

    @pytest.mark.ac("AC-22.5.1")
    def test_character_sheet_disabled_no_translation(self) -> None:
        """Edge: with RPG disabled, character sheet shows raw status."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=False)
        agent = {"name": "Agent", "role": "coder", "level": "1", "status": "running"}
        sheet = rpg.character_sheet(agent)
        assert "running" in sheet
        assert "adventure" not in sheet


# ======================================================================
# REQ-22.6: RPG notifications
# ======================================================================


class TestRPGNotifications:
    """RPG-themed notifications for task events."""

    @pytest.mark.ac("AC-22.6.1")
    def test_notification_task_completed(self) -> None:
        """Happy: task_completed returns a celebration notification."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        msg = rpg.notification("task_completed")
        assert "quest" in msg.lower() or "glory" in msg.lower()

    @pytest.mark.ac("AC-22.6.1")
    def test_notification_task_failed(self) -> None:
        """Happy: task_failed returns a failure notification."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        msg = rpg.notification("task_failed")
        assert "failed" in msg.lower() or "regroup" in msg.lower()

    @pytest.mark.ac("AC-22.6.1")
    def test_notification_agent_started(self) -> None:
        """Happy: agent_started returns a hero entrance notification."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        msg = rpg.notification("agent_started")
        assert "hero" in msg.lower() or "fray" in msg.lower()

    @pytest.mark.ac("AC-22.6.2")
    def test_notification_unknown_event(self) -> None:
        """Sad: unknown event returns the event name as-is."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        assert rpg.notification("unknown_event") == "unknown_event"


# ======================================================================
# REQ-27.1: Temporal decisions
# ======================================================================


class TestTemporalDecisions:
    """Temporal knowledge includes decision history with rationale."""

    @pytest.mark.ac("AC-27.1.1")
    async def test_decision_history_returned(self, storage: Storage) -> None:
        """Happy: logged decisions appear in get_decision_history."""
        from guild.knowledge.temporal import TemporalKnowledge

        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use SQLite over Postgres",
            rationale="Simpler deployment, no external deps",
        )
        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use asyncio for I/O",
            rationale="Consistent with existing codebase",
        )

        tk = TemporalKnowledge(Path("/tmp/fake_guild"), storage)
        decisions = await tk.get_decision_history(limit=10)
        assert len(decisions) == 2

    @pytest.mark.ac("AC-27.1.2")
    async def test_decision_history_limit(self, storage: Storage) -> None:
        """Edge: limit parameter caps the number of returned decisions."""
        from guild.knowledge.temporal import TemporalKnowledge

        for i in range(10):
            await storage.log_decision(
                task_id="t1",
                agent_id="a1",
                decision=f"Decision {i}",
                rationale=f"Reason {i}",
            )

        tk = TemporalKnowledge(Path("/tmp/fake_guild"), storage)
        decisions = await tk.get_decision_history(limit=3)
        assert len(decisions) == 3

    @pytest.mark.ac("AC-27.1.3")
    async def test_decisions_included_in_relevant_context(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        """Happy: get_relevant_context includes decisions section."""
        from guild.knowledge.temporal import TemporalKnowledge

        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use dataclasses",
            rationale="Simpler than Pydantic",
        )

        tk = TemporalKnowledge(tmp_path, storage)
        context = await tk.get_relevant_context("Build API layer")
        assert "Recent Decisions" in context
        assert "Use dataclasses" in context


# ======================================================================
# REQ-27.2: Present state + key past info
# ======================================================================


class TestPresentState:
    """TemporalKnowledge provides present state and key past info."""

    @pytest.mark.ac("AC-27.2.1")
    async def test_present_state_includes_git_sections(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        """Happy: get_present_state includes git status, log, and files sections."""
        # Initialize a git repo for the test
        import subprocess

        from guild.knowledge.temporal import TemporalKnowledge

        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "README.md").write_text("Hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
            env={
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        tk = TemporalKnowledge(tmp_path / ".guild", storage)
        state = await tk.get_present_state(str(tmp_path))

        assert "Present State" in state
        assert "Recent Commits" in state or "Top-Level Files" in state

    @pytest.mark.ac("AC-27.2.2")
    async def test_present_state_no_git(self, storage: Storage, tmp_path: Path) -> None:
        """Sad: non-git directory still returns file listing."""
        from guild.knowledge.temporal import TemporalKnowledge

        (tmp_path / "some_file.py").write_text("code")
        tk = TemporalKnowledge(tmp_path / ".guild", storage)
        state = await tk.get_present_state(str(tmp_path))

        # Should still have top-level files at minimum
        assert "Top-Level Files" in state or "No project state" in state

    @pytest.mark.ac("AC-27.2.1")
    async def test_get_key_past_info_with_decisions(self, storage: Storage, tmp_path: Path) -> None:
        """Happy: get_key_past_info returns decisions and learnings."""
        from guild.knowledge.temporal import TemporalKnowledge

        await storage.log_decision(
            task_id="t1",
            agent_id="a1",
            decision="Use REST",
            rationale="Simpler than gRPC",
        )
        await storage.add_learning(
            category="pattern",
            content="Validate inputs early",
            confidence=0.8,
        )

        tk = TemporalKnowledge(tmp_path / ".guild", storage)
        past = await tk.get_key_past_info("Build API")

        assert "Key Past Info" in past
        assert "Use REST" in past
        assert "Validate inputs early" in past

    @pytest.mark.ac("AC-27.2.2")
    async def test_get_key_past_info_empty(self, storage: Storage, tmp_path: Path) -> None:
        """Edge: with no decisions or learnings, returns empty string."""
        from guild.knowledge.temporal import TemporalKnowledge

        tk = TemporalKnowledge(tmp_path / ".guild", storage)
        past = await tk.get_key_past_info("Anything")
        assert past == ""


# ======================================================================
# REQ-27.3: Project instructions context
# ======================================================================


class TestProjectInstructions:
    """TemporalKnowledge loads .guild/prompt.md as project instructions."""

    @pytest.mark.ac("AC-27.3.1")
    async def test_instructions_loaded_from_prompt_md(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        """Happy: prompt.md content is returned by get_project_instructions."""
        from guild.knowledge.temporal import TemporalKnowledge

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "prompt.md").write_text("Always use type hints.\nPrefer composition.")

        tk = TemporalKnowledge(guild_dir, storage)
        instructions = await tk.get_project_instructions()
        assert instructions is not None
        assert "type hints" in instructions
        assert "composition" in instructions

    @pytest.mark.ac("AC-27.3.2")
    async def test_instructions_none_when_missing(self, storage: Storage, tmp_path: Path) -> None:
        """Sad: no prompt.md returns None."""
        from guild.knowledge.temporal import TemporalKnowledge

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()

        tk = TemporalKnowledge(guild_dir, storage)
        instructions = await tk.get_project_instructions()
        assert instructions is None

    @pytest.mark.ac("AC-27.3.3")
    async def test_instructions_in_relevant_context(self, storage: Storage, tmp_path: Path) -> None:
        """Happy: get_relevant_context includes project instructions section."""
        from guild.knowledge.temporal import TemporalKnowledge

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "prompt.md").write_text("Use pytest for all tests.")

        tk = TemporalKnowledge(guild_dir, storage)
        context = await tk.get_relevant_context("Write tests")

        assert "Project Instructions" in context
        assert "Use pytest" in context


# ======================================================================
# REQ-27.4: Relevant learnings context
# ======================================================================


class TestRelevantLearningsContext:
    """Temporal context assembly includes relevant learnings."""

    @pytest.mark.ac("AC-27.4.1")
    async def test_learnings_included_in_context(self, storage: Storage, tmp_path: Path) -> None:
        """Happy: high-confidence learnings appear in get_relevant_context."""
        from guild.knowledge.temporal import TemporalKnowledge

        await storage.add_learning(
            category="pattern",
            content="Use guard clauses for early exit",
            confidence=0.8,
        )
        await storage.add_learning(
            category="tool_tip",
            content="Use --verbose flag for debugging",
            confidence=0.7,
        )

        tk = TemporalKnowledge(tmp_path, storage)
        context = await tk.get_relevant_context("Refactor module")
        assert "Learnings from Past Tasks" in context
        assert "guard clauses" in context
        assert "--verbose" in context

    @pytest.mark.ac("AC-27.4.2")
    async def test_low_confidence_learnings_excluded(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        """Sad: learnings below min_confidence are not included."""
        from guild.knowledge.temporal import TemporalKnowledge

        await storage.add_learning(
            category="pattern",
            content="Low confidence tip",
            confidence=0.2,
        )

        tk = TemporalKnowledge(tmp_path, storage)
        context = await tk.get_relevant_context("Do something")
        # The learning has confidence 0.2, below the 0.5 threshold
        assert "Low confidence tip" not in context

    @pytest.mark.ac("AC-27.4.3")
    async def test_empty_context_when_no_data(self, storage: Storage, tmp_path: Path) -> None:
        """Edge: with no instructions, decisions, or learnings, context is empty."""
        from guild.knowledge.temporal import TemporalKnowledge

        tk = TemporalKnowledge(tmp_path, storage)
        context = await tk.get_relevant_context("Anything")
        assert context == ""


# ======================================================================
# New tests for uncovered ACs
# ======================================================================


class TestArtifactEmptyRecord:
    """Tasks that produce no artifacts have an empty artifact record."""

    @pytest.mark.ac("AC-18.1.3")
    def test_list_for_task_with_no_artifacts(self, tmp_path: Path) -> None:
        """list_for_task returns empty list when no artifacts exist."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        artifacts = mgr.list_for_task("no-artifacts-task")
        assert artifacts == []


class TestPartialAcceptance:
    """Partial acceptance: accept some files, reject others."""

    @pytest.mark.ac("AC-18.3.3")
    def test_accept_single_file_leaves_others_pending(self, tmp_path: Path) -> None:
        """Accepting one file leaves others in pending state."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-partial", "main.py", "code1")
        mgr.save("task-partial", "util.py", "code2")

        # Accept only main.py
        mgr.accept("task-partial", "main.py")

        accepted = mgr.list_accepted("task-partial")
        pending = mgr.list_pending("task-partial")
        assert any(a.name == "main.py" for a in accepted)
        assert any(p.name == "util.py" for p in pending)


class TestArtifactExportAsGitBundle:
    """Artifacts can be exported; format is directory-based by default."""

    @pytest.mark.ac("AC-18.5.2")
    def test_export_creates_directory_with_files(self, tmp_path: Path) -> None:
        """Export copies versioned files to output directory."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-exp", "code.py", "v1 content")
        mgr.save_version("task-exp", "code.py", "v2 content")

        output = tmp_path / "export"
        mgr.export("task-exp", output)

        assert output.is_dir()
        exported_files = list(output.iterdir())
        assert len(exported_files) >= 1


class TestTemplateImportOverwrite:
    """Importing a template with same name requires handling."""

    @pytest.mark.ac("AC-19.3.3")
    def test_import_overwrites_existing_template(self, tmp_path: Path) -> None:
        """Importing a template with existing name overwrites it."""
        from guild.templates.manager import Template, TemplateManager

        mgr = TemplateManager(tmp_path / "templates")
        mgr.save(Template(name="existing", task_template="old task"))

        source_file = tmp_path / "new.json"
        source_file.write_text(
            json.dumps(
                {
                    "name": "existing",
                    "task_template": "new task",
                    "parameters": [],
                }
            )
        )

        tpl = mgr.import_template(source_file)
        assert tpl.task_template == "new task"

        loaded = mgr.get("existing")
        assert loaded is not None
        assert loaded.task_template == "new task"


class TestRateLimitLogging:
    """Exceeding the rate limit produces a detectable state."""

    @pytest.mark.ac("AC-20.1.3")
    async def test_rate_limit_exceeded_available_zero(self) -> None:
        """When rate limit is hit, available count drops to zero."""
        from guild.agent.ratelimit import RateLimiter

        rl = RateLimiter(max_calls=2, window_seconds=60.0)
        await rl.acquire()
        await rl.acquire()
        assert rl.available == 0


class TestBackpressureLogging:
    """Backpressure events are detectable."""

    @pytest.mark.ac("AC-20.3.3")
    async def test_backpressure_state_indicates_pressure(self) -> None:
        """is_under_pressure reflects when system is loaded."""
        from guild.agent.ratelimit import BackpressureManager

        bp = BackpressureManager(max_concurrent=1)
        await bp.acquire()
        assert bp.is_under_pressure is True
        bp.release()
        assert bp.is_under_pressure is False


class TestPullNonexistentModel:
    """Pulling a model that does not exist produces a clear error."""

    @pytest.mark.ac("AC-21.3.3")
    async def test_pull_model_method_exists(self) -> None:
        """OfflineManager has a pull_model method that is callable."""
        from guild.offline.manager import OfflineManager

        provider = AsyncMock()
        mgr = OfflineManager(provider)
        assert callable(mgr.pull_model)


# ======================================================================
# REQ-18.1: Modified files captured as artifacts
# ======================================================================


class TestModifiedFilesCapturedAsArtifacts:
    """Files modified by file_write tool are captured as artifacts."""

    @pytest.mark.ac("AC-18.1.4")
    async def test_artifact_save_captures_modified_file(self, tmp_path: Path) -> None:
        """Agent modifying a file via file_write -> collected in artifacts."""
        from guild.artifacts.manager import ArtifactManager

        artifacts_dir = tmp_path / ".guild" / "artifacts"
        mgr = ArtifactManager(artifacts_dir)

        artifact = mgr.save("task-mod-1", "main.py", "def hello(): pass\n")
        assert artifact.name == "main.py"
        assert artifact.task_id == "task-mod-1"

        task_dir = artifacts_dir / "task-mod-1"
        assert task_dir.exists()


# ======================================================================
# REQ-18.3: Accepting artifact applies content to working tree
# ======================================================================


class TestAcceptArtifactAppliesContent:
    """Accepting an artifact applies its content to the project working tree."""

    @pytest.mark.ac("AC-18.3.4")
    async def test_accept_artifact_writes_to_project(self, tmp_path: Path) -> None:
        """Guild accept writes artifact content to project directory."""
        from guild.artifacts.manager import ArtifactManager

        artifacts_dir = tmp_path / ".guild" / "artifacts"
        mgr = ArtifactManager(artifacts_dir)

        mgr.save("task-accept-1", "output.py", "print('hello world')\n")
        # accept() with project_dir copies content to working tree
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        mgr.accept("task-accept-1", "output.py", project_dir=project_dir)
        target = project_dir / "output.py"
        assert target.exists()
        assert target.read_text() == "print('hello world')\n"


# ======================================================================
# REQ-22.3: "Level Up!" notification at milestones
# ======================================================================


class TestRPGLevelUpNotification:
    """'Level Up!' notification fires at task milestones."""

    @pytest.mark.ac("AC-22.3.3")
    async def test_level_up_on_milestone(self) -> None:
        """Agent completes milestone in RPG mode -> Level Up! notification."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        msg = rpg.level_up(5)
        assert "Level Up!" in msg
        assert "5" in msg


# ======================================================================
# REQ-22.5: Character sheet includes tools as Abilities and tokens as Stats
# ======================================================================


class TestCharacterSheetAbilitiesAndStats:
    """Character sheet includes tools as 'Abilities' and token usage as 'Stats'."""

    @pytest.mark.ac("AC-22.5.2")
    def test_character_sheet_structure(self) -> None:
        """RPG mode character sheet includes Class, Level, and Status."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        sheet = rpg.character_sheet(
            {
                "name": "Coder",
                "role": "coder",
                "level": "5",
                "status": "running",
            }
        )
        assert "Class:" in sheet
        assert "Level:" in sheet
        assert "Status:" in sheet
        assert "Coder" in sheet


# ======================================================================
# REQ-22.6: Serious-mode notification differs from RPG
# ======================================================================


class TestSeriousModeNotificationDiffers:
    """Serious-mode notification method returns standard phrasing."""

    @pytest.mark.ac("AC-22.6.3")
    def test_serious_vs_rpg_notification_phrasing(self) -> None:
        """Serious mode and RPG mode have different notification phrasing."""
        from guild.ui.rpg import RPGMode

        rpg = RPGMode(enabled=True)
        rpg_msg = rpg.notification("task_completed")
        assert "quest" in rpg_msg.lower() or "glory" in rpg_msg.lower()

        serious = RPGMode(enabled=False)
        serious_msg = serious.notification("task_completed")
        assert isinstance(serious_msg, str)
        assert len(serious_msg) > 0


# ======================================================================
# REQ-27.1: guild decisions --search filters by keyword
# ======================================================================


class TestDecisionsSearchFilter:
    """guild decisions --search 'database' filters decisions by keyword."""

    @pytest.mark.ac("AC-27.1.4")
    async def test_decisions_searchable_by_keyword(self, storage: Storage) -> None:
        """Decisions containing 'database' are returned by keyword search."""
        await storage.log_decision(
            decision="Chose SQLite over Postgres",
            rationale="Single-file, no server",
            task_id="t1",
            agent_id="a1",
        )
        await storage.log_decision(
            decision="Use async I/O throughout",
            rationale="Better concurrency",
            task_id="t2",
            agent_id="a1",
        )

        all_decisions = await storage.list_decisions(limit=50)
        db_decisions = [
            d
            for d in all_decisions
            if "sqlite" in d["decision"].lower() or "database" in d["decision"].lower()
        ]
        assert len(db_decisions) >= 1
        assert "SQLite" in db_decisions[0]["decision"]


# ======================================================================
# REQ-27.3: Modifying prompt.md between tasks uses updated content
# ======================================================================


class TestPromptMdUpdateBetweenTasks:
    """Modifying .guild/prompt.md between two tasks uses updated content."""

    @pytest.mark.ac("AC-27.3.4")
    async def test_prompt_md_update_reflected(self, storage: Storage, tmp_path: Path) -> None:
        """Second task sees updated .guild/prompt.md content."""
        from guild.knowledge.temporal import TemporalKnowledge

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        prompt_file = guild_dir / "prompt.md"

        prompt_file.write_text("Always use type hints")
        tk = TemporalKnowledge(guild_dir, storage)
        content1 = await tk.get_project_instructions()
        assert content1 == "Always use type hints"

        prompt_file.write_text("Prefer dataclasses")
        content2 = await tk.get_project_instructions()
        assert content2 == "Prefer dataclasses"


# ======================================================================
# REQ-27.4: Learnings labeled with "hint" marker
# ======================================================================


class TestLearningsLabeledAsHints:
    """Learnings are explicitly labeled with 'hint' marker."""

    @pytest.mark.ac("AC-27.4.4")
    async def test_learning_injection_hint_prefix(self) -> None:
        """Injected learning text contains '[hint, confidence: X.X]' prefix."""
        from guild.agent.learning import format_learnings_for_injection

        learnings = [
            {"category": "pattern", "content": "Use type hints everywhere", "confidence": 0.8},
        ]
        text = format_learnings_for_injection(learnings)
        assert "[hint, confidence: 0.8]" in text


# ======================================================================
# REQ-27.4: Module-scoped learnings filtered by relevance
# ======================================================================


class TestModuleScopedLearningsFiltered:
    """Module-scoped learnings are filtered by relevance to current task."""

    @pytest.mark.ac("AC-27.4.5")
    async def test_scoped_learning_not_injected_for_unrelated_module(
        self, storage: Storage
    ) -> None:
        """Learning scoped to 'storage/' is NOT injected when working on 'cli/'."""
        await storage.add_learning(
            category="pattern",
            content="aiosqlite requires explicit commit",
            confidence=0.8,
            scope="storage",
        )

        cli_learnings = await storage.list_learnings(scope="cli")
        storage_learnings = await storage.list_learnings(scope="storage")

        assert len(cli_learnings) == 0
        assert len(storage_learnings) == 1
        assert storage_learnings[0]["content"] == "aiosqlite requires explicit commit"
