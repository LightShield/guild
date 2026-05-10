"""REST API server — requires fastapi + uvicorn (REQ-05.4, REQ-05.5).

Serves the Guild web UI (static files from ui/dist/) and provides JSON API
routes backed by Storage for tasks, agents, config, audit, and learnings.
Includes WebSocket endpoint for real-time status updates.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from guild import __version__
from guild.config.loader import DB_FILENAME
from guild.task.spec import TaskStatus

__all__ = ["API_ROUTES", "create_app"]

logger = logging.getLogger(__name__)

_WEBSOCKET_POLL_SECONDS = 2

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


async def _get_current_status(storage: Any) -> dict[str, Any]:
    """Gather current status for WebSocket broadcast."""
    summary = await storage.get_token_summary()
    tasks = await storage.list_tasks()
    agents = await storage.list_agents()
    return {
        "status": "ok",
        "version": __version__,
        "task_count": summary["task_count"],
        "agent_count": summary["agent_count"],
        "total_input_tokens": summary["total_input"],
        "total_output_tokens": summary["total_output"],
        "tasks": tasks,
        "agents": agents,
    }


def _register_task_routes(app: Any, get_storage: Callable[[], Any]) -> None:
    """Register task-related API routes."""
    _register_task_query_routes(app, get_storage)
    _register_task_action_routes(app, get_storage)


def _register_task_query_routes(app: Any, get_storage: Callable[[], Any]) -> None:
    """Register task query (GET/POST create) routes."""
    from fastapi import HTTPException, Request  # type: ignore[import-untyped]

    @app.get("/api/tasks")
    async def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        storage = get_storage()
        return await storage.list_tasks(status=status)

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        """Return a single task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.post("/api/tasks")
    async def create_task(request: Request) -> dict[str, Any]:
        """Create a new task from a JSON body with a 'description' field."""
        import uuid

        storage = get_storage()
        body = await request.json()
        description = body.get("description", "")
        if not description:
            raise HTTPException(status_code=400, detail="description is required")
        task_id = str(uuid.uuid4())
        await storage.create_task(task_id, description)
        await storage.log_audit("task_created", details=f"task_id={task_id}")
        return {"id": task_id, "status": TaskStatus.PENDING, "description": description}


def _register_task_action_routes(app: Any, get_storage: Callable[[], Any]) -> None:
    """Register task action (kill/pause/resume) routes."""
    from fastapi import HTTPException  # type: ignore[import-untyped]

    @app.post("/api/tasks/{task_id}/kill")
    async def kill_task(task_id: str) -> dict[str, str]:
        """Kill a running task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.KILLED)
        await storage.log_audit("task_killed", details=f"task_id={task_id}")
        return {"id": task_id, "action": TaskStatus.KILLED}

    @app.post("/api/tasks/{task_id}/pause")
    async def pause_task(task_id: str) -> dict[str, str]:
        """Pause a running task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.PAUSED)
        await storage.log_audit("task_paused", details=f"task_id={task_id}")
        return {"id": task_id, "action": TaskStatus.PAUSED}

    @app.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str) -> dict[str, str]:
        """Resume a paused task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.RUNNING)
        await storage.log_audit("task_resumed", details=f"task_id={task_id}")
        return {"id": task_id, "action": "resumed"}


def _register_agent_routes(app: Any, get_storage: Callable[[], Any]) -> None:
    """Register agent-related API routes."""

    @app.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """List all registered agents."""
        storage = get_storage()
        return await storage.list_agents()


def _register_config_routes(app: Any, get_storage: Callable[[], Any], guild_dir: Path) -> None:
    """Register config, blocks, teams, learnings, and audit API routes."""
    _register_status_routes(app, get_storage, guild_dir)
    _register_config_crud_routes(app, guild_dir)


def _register_status_routes(app: Any, get_storage: Callable[[], Any], guild_dir: Path) -> None:
    """Register status, learnings, and audit routes."""

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        """Return project status with token usage summaries."""
        storage = get_storage()
        summary = await storage.get_token_summary()
        return {
            "status": "ok",
            "version": __version__,
            "task_count": summary["task_count"],
            "agent_count": summary["agent_count"],
            "total_input_tokens": summary["total_input"],
            "total_output_tokens": summary["total_output"],
        }

    @app.get("/api/blocks")
    async def list_blocks() -> list[dict[str, str]]:
        """List available block definitions."""
        try:
            from guild.blocks.registry import BlockRegistry

            registry = BlockRegistry()
            return [{"name": name} for name in registry.list_blocks()]
        except Exception:
            return []

    @app.get("/api/teams")
    async def list_teams() -> list[dict[str, str]]:
        """List configured team compositions."""
        try:
            from guild.config.loader import load_config

            config = load_config(guild_dir)
            return [{"name": t.name} for t in (config.teams or [])]
        except Exception:
            return []

    @app.get("/api/learnings")
    async def list_learnings() -> list[dict[str, Any]]:
        """List all stored learnings."""
        storage = get_storage()
        return await storage.list_learnings()

    @app.get("/api/audit")
    async def get_audit(limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit log entries."""
        storage = get_storage()
        return await storage.list_audit(limit=limit)


def _register_config_crud_routes(app: Any, guild_dir: Path) -> None:
    """Register config GET/POST routes."""
    from fastapi import Request  # type: ignore[import-untyped]

    from guild.config.loader import load_config

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        """Return the current Guild configuration."""
        try:
            config = load_config(guild_dir)
            return config.model_dump() if hasattr(config, "model_dump") else {}
        except Exception as exc:
            logger.warning("Failed to load config: %s", exc)
            return {}

    @app.post("/api/config")
    async def post_config(request: Request) -> dict[str, str]:
        """Update Guild configuration (not yet implemented)."""
        await request.json()
        return {"status": "ok", "message": "Config update not yet implemented"}


def _register_websocket(app: Any, get_storage: Callable[[], Any]) -> None:
    """Register the WebSocket endpoint for real-time updates (REQ-05.5)."""
    from fastapi import WebSocket, WebSocketDisconnect  # type: ignore[import-untyped]

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Send status updates every 2 seconds to connected clients."""
        await websocket.accept()
        try:
            while True:
                storage = get_storage()
                data = await _get_current_status(storage)
                await websocket.send_json(data)
                await asyncio.sleep(_WEBSOCKET_POLL_SECONDS)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("WebSocket closed unexpectedly", exc_info=True)


def _register_static_files(app: Any) -> None:
    """Register static file serving for the built Svelte UI."""
    from fastapi.responses import FileResponse  # type: ignore[import-untyped]
    from fastapi.staticfiles import StaticFiles  # type: ignore[import-untyped]

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


def create_app(
    guild_dir: Path | None = None,
    storage: Any | None = None,
) -> Any:
    """Create the FastAPI app. Raises ImportError if fastapi not installed.

    Args:
        guild_dir: Path to .guild/ directory for accessing Storage.
                   If None, uses .guild/ in current working directory.
        storage: Optional pre-connected Storage instance (for testing).
                 When provided, the lifespan will not create/close storage.
    """
    try:
        from fastapi import FastAPI  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("Install fastapi for API support: pip install guild[api]") from exc

    from guild.config.loader import find_guild_dir
    from guild.storage.sqlite import Storage

    # Resolve guild directory
    _guild_dir = guild_dir or find_guild_dir() or Path.cwd() / ".guild"
    _db_path = _guild_dir / DB_FILENAME

    _injected_storage = storage

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage Storage lifecycle: connect on startup, close on shutdown."""
        if _injected_storage is not None:  # pragma: no cover — injected storage path for testing
            app.state.storage = _injected_storage
            app.state.guild_dir = _guild_dir
            logger.info("API using injected storage for %s", _guild_dir)
            yield
            return
        store = Storage(_db_path)
        await store.connect()
        app.state.storage = store
        app.state.guild_dir = _guild_dir
        logger.info("API storage connected: %s", _db_path)
        yield
        await store.close()
        logger.info("API storage closed for %s", _db_path)

    app = FastAPI(title="Guild", version=__version__, lifespan=lifespan)

    def _get_storage() -> Storage:
        """Retrieve Storage from app state."""
        return app.state.storage

    # Register route groups
    _register_task_routes(app, _get_storage)
    _register_agent_routes(app, _get_storage)
    _register_config_routes(app, _get_storage, _guild_dir)
    _register_websocket(app, _get_storage)
    _register_static_files(app)

    return app
