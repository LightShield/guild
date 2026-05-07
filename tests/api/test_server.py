"""Tests for the REST API server (REQ-05.4)."""

from unittest.mock import patch

import pytest

from guild.api.server import API_ROUTES, create_app


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
