"""Tests for A2A (Agent-to-Agent) protocol gateway (REQ-04.7a).

Written BEFORE implementation (TDD red phase).
Google A2A spec: HTTP JSON-RPC for agent discovery and task lifecycle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def a2a_app(tmp_path: Path) -> Any:
    """Create a Guild app with A2A gateway enabled."""
    from guild.api.server import create_app

    guild_dir = tmp_path / ".guild"
    guild_dir.mkdir()
    (guild_dir / "config.toml").write_text(
        '[provider]\nname = "ollama"\nmodel = "test"\n'
        'base_url = "http://localhost:11434"\n'
    )
    return create_app(guild_dir=guild_dir)


class TestAgentCardDiscovery:
    """A2A agent card at /.well-known/agent.json."""

    def test_agent_card_returns_valid_json(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        card = resp.json()
        assert card["name"] == "Guild"
        assert "description" in card
        assert "url" in card
        assert "capabilities" in card

    def test_agent_card_lists_supported_methods(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.get("/.well-known/agent.json")
        card = resp.json()
        methods = card["capabilities"]["methods"]
        assert "tasks/send" in methods
        assert "tasks/get" in methods
        assert "tasks/cancel" in methods

    def test_agent_card_includes_version(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.get("/.well-known/agent.json")
        card = resp.json()
        assert "version" in card


class TestA2ATaskSend:
    """A2A tasks/send — create a task via JSON-RPC."""

    def test_send_creates_task_and_returns_submitted(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {
                        "message": {"role": "user", "parts": [{"text": "Fix the login bug"}]},
                    },
                    "id": "req-1",
                },
            )
        assert resp.status_code == 200
        result = resp.json()
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "req-1"
        task = result["result"]
        assert "id" in task
        assert task["status"]["state"] == "submitted"

    def test_send_without_message_returns_error(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {},
                    "id": "req-2",
                },
            )
        assert resp.status_code == 200
        result = resp.json()
        assert "error" in result
        assert result["error"]["code"] == -32602  # Invalid params


class TestA2ATaskGet:
    """A2A tasks/get — retrieve task status."""

    def test_get_returns_task_status(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            # First create a task
            send_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {
                        "message": {"role": "user", "parts": [{"text": "hello"}]},
                    },
                    "id": "req-3",
                },
            )
            task_id = send_resp.json()["result"]["id"]

            # Then get its status
            get_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "params": {"id": task_id},
                    "id": "req-4",
                },
            )
        assert get_resp.status_code == 200
        result = get_resp.json()["result"]
        assert result["id"] == task_id
        assert "status" in result

    def test_get_nonexistent_task_returns_error(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/get",
                    "params": {"id": "nonexistent-id"},
                    "id": "req-5",
                },
            )
        assert resp.status_code == 200
        result = resp.json()
        assert "error" in result
        assert result["error"]["code"] == -32001  # Task not found


class TestA2ATaskCancel:
    """A2A tasks/cancel — cancel a running task."""

    def test_cancel_sets_task_canceled(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            # Create a task
            send_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {
                        "message": {"role": "user", "parts": [{"text": "long task"}]},
                    },
                    "id": "req-6",
                },
            )
            task_id = send_resp.json()["result"]["id"]

            # Cancel it
            cancel_resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "params": {"id": task_id},
                    "id": "req-7",
                },
            )
        assert cancel_resp.status_code == 200
        result = cancel_resp.json()["result"]
        assert result["id"] == task_id
        assert result["status"]["state"] == "canceled"

    def test_cancel_nonexistent_returns_error(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/cancel",
                    "params": {"id": "ghost-task"},
                    "id": "req-8",
                },
            )
        result = resp.json()
        assert "error" in result


class TestA2AProtocolErrors:
    """A2A JSON-RPC protocol error handling."""

    def test_unknown_method_returns_method_not_found(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/explode",
                    "params": {},
                    "id": "req-9",
                },
            )
        result = resp.json()
        assert "error" in result
        assert result["error"]["code"] == -32601  # Method not found

    def test_invalid_json_returns_parse_error(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                content=b"not json at all",
                headers={"content-type": "application/json"},
            )
        result = resp.json()
        assert "error" in result
        assert result["error"]["code"] == -32700  # Parse error

    def test_missing_method_field_returns_invalid_request(self, a2a_app: Any) -> None:
        from starlette.testclient import TestClient

        with TestClient(a2a_app) as client:
            resp = client.post(
                "/a2a",
                json={"jsonrpc": "2.0", "params": {}, "id": "req-10"},
            )
        result = resp.json()
        assert "error" in result
        assert result["error"]["code"] == -32600  # Invalid request
