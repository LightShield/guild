"""E2E acceptance tests for team execution, REST API, and A2A gateway.

Black-box tests exercising multi-agent teams and the HTTP API.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.provider.base import LLMResponse

runner = CliRunner()
pytestmark = pytest.mark.e2e


def _mock_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=LLMResponse(
        content="Step completed successfully.",
        tool_calls=None,
        input_tokens=50, output_tokens=30, model="mock",
    ))
    provider.health_check = AsyncMock(return_value=True)
    return provider


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a guild project with blocks and team definitions."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, f"guild init failed: {result.output}"

    # Create blocks directory inside .guild
    blocks_dir = tmp_path / ".guild" / "blocks"
    blocks_dir.mkdir(exist_ok=True)

    # Minimal planner block
    (blocks_dir / "planner.toml").write_text(
        '[block]\n'
        'name = "planner"\n'
        'role = "planner"\n'
        'system_prompt = "You are a planner."\n'
        'tools = []\n'
    )

    # Minimal coder block
    (blocks_dir / "coder.toml").write_text(
        '[block]\n'
        'name = "coder"\n'
        'role = "coder"\n'
        'system_prompt = "You are a coder."\n'
        'tools = ["file_write", "shell"]\n'
    )

    # Team definition: plan -> code
    (blocks_dir / "team_dev.toml").write_text(
        '[team]\n'
        'name = "dev"\n'
        'entry_block = "plan"\n'
        '\n'
        '[team.blocks]\n'
        'plan = "planner"\n'
        'code = "coder"\n'
        '\n'
        '[[team.connections]]\n'
        'source_block = "plan"\n'
        'source_port = "output"\n'
        'target_block = "code"\n'
        'target_port = "input"\n'
    )

    return tmp_path


# REQ-04.1: team execution
@pytest.mark.req("REQ-04.1")
class TestTeamExecution:
    """Team pipeline execution through the CLI."""

    def test_team_command_runs_pipeline(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Guild team runs planner->coder pipeline."""
        monkeypatch.chdir(project_dir)
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(
                app, ["team", "Build hello world", "--team", "dev"],
            )
        assert result.exit_code == 0, f"team command failed: {result.output}"
        assert "Team done" in result.output

    def test_team_not_found_errors(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sad path: nonexistent team name."""
        monkeypatch.chdir(project_dir)
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            result = runner.invoke(
                app, ["team", "Do something", "--team", "nonexistent"],
            )
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_team_no_project_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sad path: no guild project."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["team", "Something"])
        assert result.exit_code == 1

    def test_team_subtasks_appear_in_history(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After team runs, sub-tasks are visible in guild history."""
        monkeypatch.chdir(project_dir)
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            runner.invoke(app, ["team", "Build hello world", "--team", "dev"])

        # Observable outcome: sub-tasks visible in history
        history = runner.invoke(app, ["history"], terminal_width=200)
        assert history.exit_code == 0
        # Should show tasks for the team blocks (planner and/or coder)
        assert (
            "completed" in history.output.lower()
            or "planner" in history.output.lower()
            or "coder" in history.output.lower()
        )

    def test_team_audit_trail_logged(
        self, project_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After team runs, audit trail contains task_created entries."""
        monkeypatch.chdir(project_dir)
        with patch(
            "guild.cli.task_runner.create_resilient_provider",
            return_value=_mock_provider(),
        ):
            runner.invoke(app, ["team", "Build something", "--team", "dev"])

        audit = runner.invoke(app, ["audit"], terminal_width=200)
        assert audit.exit_code == 0
        assert "task_created" in audit.output or "task_completed" in audit.output


# REQ-05.4: REST API
@pytest.mark.req("REQ-05.4")
class TestRestApi:
    """REST API endpoint tests using Starlette test client."""

    def test_api_status_endpoint(self, project_dir: Path) -> None:
        """GET /api/status returns project info."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.get("/api/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_api_create_and_list_task(self, project_dir: Path) -> None:
        """POST /api/tasks creates, GET /api/tasks lists."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            create_resp = client.post(
                "/api/tasks", json={"description": "API task"},
            )
            assert create_resp.status_code == 200

            list_resp = client.get("/api/tasks")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) >= 1


# REQ-04.7a: A2A gateway
@pytest.mark.req("REQ-04.7a")
class TestA2AGateway:
    """A2A protocol gateway tests."""

    def test_agent_card_discovery(self, project_dir: Path) -> None:
        """GET /.well-known/agent.json returns valid agent card."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "Guild"
        assert "tasks/send" in card["capabilities"]["methods"]

    def test_a2a_task_lifecycle(self, project_dir: Path) -> None:
        """Send task via A2A, get status, cancel."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            # Send
            send_resp = client.post("/a2a", json={
                "jsonrpc": "2.0", "method": "tasks/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"text": "Hello"}],
                    },
                },
                "id": "1",
            })
            assert send_resp.status_code == 200
            task_id = send_resp.json()["result"]["id"]

            # Get
            get_resp = client.post("/a2a", json={
                "jsonrpc": "2.0", "method": "tasks/get",
                "params": {"id": task_id}, "id": "2",
            })
            assert get_resp.json()["result"]["id"] == task_id

            # Cancel
            cancel_resp = client.post("/a2a", json={
                "jsonrpc": "2.0", "method": "tasks/cancel",
                "params": {"id": task_id}, "id": "3",
            })
            assert cancel_resp.json()["result"]["status"]["state"] == "canceled"

    def test_a2a_invalid_method_errors(self, project_dir: Path) -> None:
        """Sad path: unknown method."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.post("/a2a", json={
                "jsonrpc": "2.0", "method": "invalid/method",
                "params": {}, "id": "99",
            })
        assert resp.json()["error"]["code"] == -32601
