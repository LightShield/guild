"""REST API server — requires fastapi + uvicorn (REQ-05.4).

Serves the Guild web UI (static files from ui/dist/) and provides JSON API
routes backed by Storage for tasks, agents, config, audit, and learnings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = ["API_ROUTES", "create_app"]

logger = logging.getLogger(__name__)

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
    "POST /api/config": "Update config",
    "POST /api/tasks/{id}/kill": "Kill a task",
    "POST /api/tasks/{id}/pause": "Pause a task",
    "POST /api/tasks/{id}/resume": "Resume a task",
    "WS /ws": "WebSocket for real-time updates",
}

# Path to built frontend assets (relative to project root)
_UI_DIST = Path(__file__).resolve().parent.parent.parent.parent / "ui" / "dist"


def create_app(guild_dir: Path | None = None) -> Any:
    """Create the FastAPI app. Raises ImportError if fastapi not installed.

    Args:
        guild_dir: Path to .guild/ directory for accessing Storage.
                   If None, uses .guild/ in current working directory.
    """
    try:
        from fastapi import FastAPI, HTTPException, Request  # type: ignore[import-untyped]
        from fastapi.responses import FileResponse  # type: ignore[import-untyped]
        from fastapi.staticfiles import StaticFiles  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("Install fastapi for API support: pip install guild[api]") from exc

    from guild.config.loader import find_guild_dir, load_config
    from guild.storage.sqlite import Storage

    app = FastAPI(title="Guild", version="0.2.0")

    # Resolve guild directory
    _guild_dir = guild_dir or find_guild_dir() or Path.cwd() / ".guild"
    _db_path = _guild_dir / "guild.db"
    _storage: Storage | None = None

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal _storage
        _storage = Storage(_db_path)
        await _storage.connect()
        logger.info("API storage connected: %s", _db_path)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if _storage:
            await _storage.close()

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        assert _storage is not None
        summary = await _storage.get_token_summary()
        return {
            "status": "ok",
            "version": "0.2.0",
            "task_count": summary["task_count"],
            "agent_count": summary["agent_count"],
            "total_input_tokens": summary["total_input"],
            "total_output_tokens": summary["total_output"],
        }

    @app.get("/api/tasks")
    async def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
        assert _storage is not None
        return await _storage.list_tasks(status=status)

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        assert _storage is not None
        task = await _storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.post("/api/tasks")
    async def create_task(request: Request) -> dict[str, Any]:
        assert _storage is not None
        import uuid

        body = await request.json()
        description = body.get("description", "")
        if not description:
            raise HTTPException(status_code=400, detail="description is required")
        task_id = str(uuid.uuid4())
        await _storage.create_task(task_id, description)
        await _storage.log_audit("task_created", details=f"task_id={task_id}")
        return {"id": task_id, "status": "pending", "description": description}

    @app.post("/api/tasks/{task_id}/kill")
    async def kill_task(task_id: str) -> dict[str, str]:
        assert _storage is not None
        task = await _storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await _storage.update_task(task_id, status="killed")
        await _storage.log_audit("task_killed", details=f"task_id={task_id}")
        return {"id": task_id, "action": "killed"}

    @app.post("/api/tasks/{task_id}/pause")
    async def pause_task(task_id: str) -> dict[str, str]:
        assert _storage is not None
        task = await _storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await _storage.update_task(task_id, status="paused")
        await _storage.log_audit("task_paused", details=f"task_id={task_id}")
        return {"id": task_id, "action": "paused"}

    @app.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str) -> dict[str, str]:
        assert _storage is not None
        task = await _storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await _storage.update_task(task_id, status="running")
        await _storage.log_audit("task_resumed", details=f"task_id={task_id}")
        return {"id": task_id, "action": "resumed"}

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        assert _storage is not None
        return await _storage.list_agents()

    @app.get("/api/blocks")
    async def list_blocks() -> list[dict[str, str]]:
        # Return block definitions from registry if available
        try:
            from guild.blocks.registry import BlockRegistry

            registry = BlockRegistry()
            return [{"name": name} for name in registry.list_blocks()]
        except Exception:
            return []

    @app.get("/api/teams")
    async def list_teams() -> list[dict[str, str]]:
        # Return team definitions from config if available
        try:
            config = load_config(_guild_dir)
            return [{"name": t.name} for t in (config.teams or [])]
        except Exception:
            return []

    @app.get("/api/learnings")
    async def list_learnings() -> list[dict[str, Any]]:
        assert _storage is not None
        return await _storage.list_learnings()

    @app.get("/api/audit")
    async def get_audit(limit: int = 50) -> list[dict[str, Any]]:
        assert _storage is not None
        return await _storage.list_audit(limit=limit)

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        try:
            config = load_config(_guild_dir)
            return config.model_dump() if hasattr(config, "model_dump") else {}
        except Exception as exc:
            logger.warning("Failed to load config: %s", exc)
            return {}

    @app.post("/api/config")
    async def post_config(request: Request) -> dict[str, str]:
        # Placeholder: in a full implementation this would write to config.toml
        await request.json()
        return {"status": "ok", "message": "Config update not yet implemented"}

    # ------------------------------------------------------------------
    # Static file serving (built Svelte UI)
    # ------------------------------------------------------------------

    if _UI_DIST.is_dir():
        # Serve static assets (JS, CSS, images)
        app.mount(
            "/_app",
            StaticFiles(directory=str(_UI_DIST / "_app")),
            name="svelte-app",
        )

        @app.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            """Serve the SPA — return index.html for all non-API routes."""
            file_path = _UI_DIST / path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_UI_DIST / "index.html"))

    return app
