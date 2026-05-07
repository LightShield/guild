"""REST API definition — requires fastapi to serve (REQ-05.4)."""

from __future__ import annotations

from typing import Any

__all__ = ["API_ROUTES", "create_app"]

API_ROUTES: dict[str, str] = {
    "GET /api/status": "Project status, tasks, agents",
    "GET /api/tasks": "List all tasks",
    "GET /api/tasks/{id}": "Get task details",
    "GET /api/agents": "List all agents",
    "GET /api/blocks": "List available blocks",
    "GET /api/teams": "List available teams",
    "GET /api/learnings": "List learnings",
    "GET /api/audit": "Audit log",
    "GET /api/config": "Current config",
    "POST /api/tasks": "Create a task",
    "POST /api/tasks/{id}/kill": "Kill a task",
    "POST /api/tasks/{id}/pause": "Pause a task",
    "POST /api/tasks/{id}/resume": "Resume a task",
    "WS /ws": "WebSocket for real-time updates",
}


def create_app() -> Any:
    """Create the FastAPI app. Raises ImportError if fastapi not installed."""
    try:
        from fastapi import FastAPI  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("Install fastapi for API support: pip install guild[api]") from exc

    app = FastAPI(title="Guild", version="0.2.0")

    @app.get("/api/status")
    async def get_status() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/tasks")
    async def list_tasks() -> list[dict[str, str]]:
        return []

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, str]:
        return {"id": task_id}

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, str]]:
        return []

    @app.get("/api/blocks")
    async def list_blocks() -> list[dict[str, str]]:
        return []

    @app.get("/api/teams")
    async def list_teams() -> list[dict[str, str]]:
        return []

    @app.get("/api/learnings")
    async def list_learnings() -> list[dict[str, str]]:
        return []

    @app.get("/api/audit")
    async def get_audit() -> list[dict[str, str]]:
        return []

    @app.get("/api/config")
    async def get_config() -> dict[str, str]:
        return {}

    @app.post("/api/tasks")
    async def create_task() -> dict[str, str]:
        return {"id": "new"}

    @app.post("/api/tasks/{task_id}/kill")
    async def kill_task(task_id: str) -> dict[str, str]:
        return {"id": task_id, "action": "killed"}

    @app.post("/api/tasks/{task_id}/pause")
    async def pause_task(task_id: str) -> dict[str, str]:
        return {"id": task_id, "action": "paused"}

    @app.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str) -> dict[str, str]:
        return {"id": task_id, "action": "resumed"}

    return app
