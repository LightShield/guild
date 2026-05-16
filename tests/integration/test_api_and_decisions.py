"""Integration tests for REST API, A2A gateway, and decision log.

These tests require internal guild module access (guild.api.server,
guild.storage.sqlite) and were moved from e2e/ to keep e2e/ purely black-box.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from guild.cli.main import app
from guild.storage.audit import DecisionRecord

runner = CliRunner()
pytestmark = pytest.mark.integration


@pytest.fixture()
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a guild project."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, f"guild init failed: {result.output}"
    return tmp_path


class TestRestApi:
    """REST API endpoint tests using Starlette test client."""

    @pytest.mark.ac("AC-05.4.1")
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

    @pytest.mark.ac("AC-05.4.2")
    def test_api_create_and_list_task(self, project_dir: Path) -> None:
        """POST /api/tasks creates, GET /api/tasks lists."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={"description": "API task"},
            )
            assert create_resp.status_code == 200

            list_resp = client.get("/api/tasks")
            assert list_resp.status_code == 200
            assert len(list_resp.json()) >= 1


class TestA2AGateway:
    """A2A protocol gateway tests."""

    @pytest.mark.ac("AC-04.7a.1")
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

    @pytest.mark.ac("AC-04.7a.2")
    def test_a2a_task_lifecycle(self, project_dir: Path) -> None:
        """Send task via A2A, get status, cancel."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            # Send
            send_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"text": "Hello"}],
                        },
                    },
                    "id": "1",
                },
            )
            assert send_resp.status_code == 200
            task_id = send_resp.json()["result"]["id"]

            # Get
            get_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "params": {"id": task_id},
                    "id": "2",
                },
            )
            assert get_resp.json()["result"]["id"] == task_id

            # Cancel
            cancel_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "params": {"id": task_id},
                    "id": "3",
                },
            )
            assert cancel_resp.json()["result"]["status"]["state"] == "canceled"

    @pytest.mark.ac("AC-04.7a.3")
    def test_a2a_invalid_method_errors(self, project_dir: Path) -> None:
        """Sad path: unknown method."""
        from starlette.testclient import TestClient

        from guild.api.server import create_app

        guild_dir = project_dir / ".guild"
        api_app = create_app(guild_dir=guild_dir)
        with TestClient(api_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "invalid/method",
                    "params": {},
                    "id": "99",
                },
            )
        assert resp.json()["error"]["code"] == -32601


class TestDecisionLogEntries:
    """Verify decision log entries contain alternatives and rationale."""

    @pytest.mark.ac("AC-06.12.2")
    async def test_decision_log_stores_rationale(self, project_dir: Path) -> None:
        """Decision log entry includes the rationale field."""
        from guild.storage.sqlite import Storage

        db_path = project_dir / ".guild" / "guild.db"
        store = Storage(db_path)
        await store.connect()
        await store.log_decision(
            DecisionRecord(
                task_id="t-dec",
                agent_id="a-dec",
                decision="Use SQLite",
                rationale="Simpler than Postgres, no external deps",
            )
        )
        decisions = await store.list_decisions(limit=5)
        assert len(decisions) >= 1
        assert any("SQLite" in d.get("decision", "") for d in decisions)
        await store.close()
