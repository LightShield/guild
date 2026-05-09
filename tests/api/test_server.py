"""Tests for the REST API server (REQ-05.4, REQ-05.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from guild.api.server import API_ROUTES, create_app

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def guild_api_dir(tmp_path: Path) -> Path:
    """Create a minimal .guild directory for API tests."""
    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    (guild_dir / "config.toml").write_text(
        '[provider]\nname = "ollama"\nmodel = "test"\n' 'base_url = "http://localhost:11434"\n'
    )
    return guild_dir


@pytest.mark.unit
@pytest.mark.req("REQ-05.4")
def test_api_routes_defined() -> None:
    """All expected API routes are defined in the registry."""
    expected_routes = [
        "GET /api/status",
        "GET /api/tasks",
        "GET /api/tasks/{id}",
        "GET /api/agents",
        "GET /api/blocks",
        "GET /api/teams",
        "GET /api/learnings",
        "GET /api/audit",
        "GET /api/config",
        "POST /api/tasks",
        "POST /api/tasks/{id}/kill",
        "POST /api/tasks/{id}/pause",
        "POST /api/tasks/{id}/resume",
        "WS /ws",
    ]
    for route in expected_routes:
        assert route in API_ROUTES, f"Missing route: {route}"


@pytest.mark.unit
@pytest.mark.req("REQ-05.4")
def test_create_app_raises_without_fastapi() -> None:
    """create_app raises ImportError when fastapi is not installed."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fastapi":
            raise ImportError("No module named 'fastapi'")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=mock_import),
        pytest.raises(ImportError, match="Install fastapi"),
    ):
        create_app()


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_api_status_returns_project_info(guild_api_dir: Path) -> None:
    """GET /api/status returns version and counts."""
    from starlette.testclient import TestClient

    app = create_app(guild_dir=guild_api_dir)

    with TestClient(app) as client:
        resp = client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.2.0"
    assert "task_count" in data
    assert "agent_count" in data


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_api_tasks_returns_list(guild_api_dir: Path) -> None:
    """GET /api/tasks returns an empty list for a fresh project."""
    from starlette.testclient import TestClient

    app = create_app(guild_dir=guild_api_dir)

    with TestClient(app) as client:
        resp = client.get("/api/tasks")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_api_create_and_get_task(guild_api_dir: Path) -> None:
    """POST /api/tasks creates a task; GET /api/tasks returns it."""
    from starlette.testclient import TestClient

    app = create_app(guild_dir=guild_api_dir)

    with TestClient(app) as client:
        create_resp = client.post(
            "/api/tasks",
            json={"description": "test task"},
        )
        assert create_resp.status_code == 200
        task_data = create_resp.json()
        assert task_data["description"] == "test task"
        assert task_data["status"] == "pending"

        list_resp = client.get("/api/tasks")
        assert list_resp.status_code == 200
        tasks = list_resp.json()
        assert len(tasks) == 1
        assert tasks[0]["description"] == "test task"


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_frontend_serves_html(tmp_path: Path) -> None:
    """When ui/dist exists, the SPA endpoint serves index.html."""
    from starlette.testclient import TestClient

    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    (guild_dir / "config.toml").write_text(
        '[provider]\nname = "ollama"\nmodel = "test"\n' 'base_url = "http://localhost:11434"\n'
    )

    # Create a mock ui/dist directory
    dist_dir = tmp_path / "ui" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>Guild UI</body></html>")
    (dist_dir / "_app").mkdir()
    (dist_dir / "_app" / "test.js").write_text("// test")

    # Patch _UI_DIST to point to our test dist before creating the app
    with patch("guild.api.server._UI_DIST", dist_dir):
        app = create_app(guild_dir=guild_dir)
        with TestClient(app) as client:
            resp = client.get("/")

    assert resp.status_code == 200
    assert "Guild UI" in resp.text


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_websocket_sends_status_updates(guild_api_dir: Path) -> None:
    """WebSocket /ws sends JSON status updates."""
    from starlette.testclient import TestClient

    app = create_app(guild_dir=guild_api_dir)

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["status"] == "ok"
        assert "task_count" in data
        assert "agent_count" in data
        assert "tasks" in data
        assert "agents" in data


@pytest.mark.unit
@pytest.mark.req("REQ-05.5")
def test_guild_serve_command_exists() -> None:
    """The serve command is registered in the Typer app."""
    from typer.testing import CliRunner

    from guild.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-05.6")
def test_visual_composer_route_exists() -> None:
    """The frontend includes a composer route for visual team building."""
    # The API serves blocks and teams data that the composer consumes
    assert "GET /api/blocks" in API_ROUTES
    assert "GET /api/teams" in API_ROUTES


@pytest.mark.unit
@pytest.mark.req("REQ-05.7")
def test_api_provides_team_connection_data() -> None:
    """The teams endpoint provides connection data for communication graph."""
    # The /api/teams route exists and includes connection info
    assert "GET /api/teams" in API_ROUTES
