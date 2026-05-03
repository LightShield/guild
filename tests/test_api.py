"""Tests for REST API (P1: GUI backend)."""

import asyncio

import pytest

pytestmark = pytest.mark.integration

from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with an initialized guild project."""
    from typer.testing import CliRunner
    from guild.cli.main import app as cli_app

    runner = CliRunner()
    runner.invoke(cli_app, ["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)

    from guild.api.server import create_app

    app = create_app()
    return TestClient(app)


class TestAPIStatus:
    def test_get_status(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "project" in data
        assert "tasks" in data
        assert "agents" in data

    def test_get_tasks_empty(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_agents_empty(self, client):
        r = client.get("/api/agents")
        assert r.status_code == 200
        assert r.json() == []


class TestAPIBlocks:
    def test_list_blocks(self, client):
        r = client.get("/api/blocks")
        assert r.status_code == 200
        blocks = r.json()
        names = [b["name"] for b in blocks]
        assert "coder" in names
        assert "planner" in names

    def test_list_teams(self, client):
        r = client.get("/api/teams")
        assert r.status_code == 200
        teams = r.json()
        names = [t["name"] for t in teams]
        assert "dev-loop" in names


class TestAPIConfig:
    def test_get_config(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert data["provider"]["name"] == "ollama"


class TestAPILearnings:
    def test_empty_learnings(self, client):
        r = client.get("/api/learnings")
        assert r.status_code == 200
        assert r.json() == []


class TestAPIAudit:
    def test_audit_has_init_entry(self, client):
        r = client.get("/api/audit")
        assert r.status_code == 200
        entries = r.json()
        assert any(e["action"] == "project_init" for e in entries)


class TestGUIServed:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Guild" in r.text
