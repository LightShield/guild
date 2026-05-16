"""REST API server — requires fastapi + uvicorn (REQ-05.4, REQ-05.5).

Serves the Guild web UI (static files from ui/dist/) and provides JSON API
routes backed by Storage for tasks, agents, config, audit, and learnings.
Includes WebSocket endpoint for real-time status updates.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

if TYPE_CHECKING:
    from guild.storage.sqlite import Storage

from guild import __version__
from guild.config.constants import (
    GUILD_DIR_NAME,
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    WEBSOCKET_POLL_SECONDS,
)
from guild.config.loader import DB_FILENAME
from guild.task.spec import TaskStatus

__all__ = ["API_ROUTES", "create_app"]

logger = get_logger(__name__)

API_ROUTES: dict[str, str] = {
    "GET /api/status": "Project status, tasks, agents",
    "GET /api/tasks": "List all tasks",
    "GET /api/tasks/{id}": "Get task details",
    "GET /api/agents": "List all agents",
    "GET /api/blocks": "List available blocks",
    "GET /api/teams": "List available teams",
    "POST /api/teams": "Save team composition",
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


async def _get_current_status(storage: "Storage") -> dict[str, Any]:
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


def _register_task_routes(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register task-related API routes."""
    _register_task_query_routes(app, get_storage)
    _register_task_action_routes(app, get_storage)


def _register_task_query_routes(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register task query (GET/POST create) routes."""
    from fastapi import HTTPException, Request

    @app.get("/api/tasks")  # type: ignore[untyped-decorator]
    async def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        storage = get_storage()
        return await storage.list_tasks(status=status)

    @app.get("/api/tasks/{task_id}")  # type: ignore[untyped-decorator]
    async def get_task(task_id: str) -> dict[str, Any]:
        """Return a single task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        return task

    @app.post("/api/tasks")  # type: ignore[untyped-decorator]
    async def create_task(request: Request) -> dict[str, Any]:
        """Create a new task from a JSON body with a 'description' field."""
        import uuid

        storage = get_storage()
        body = await request.json()
        description = body.get("description", "")
        if not description:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="description is required")
        task_id = str(uuid.uuid4())
        await storage.create_task(task_id, description)
        await storage.log_audit("task_created", details=f"task_id={task_id}")
        return {"id": task_id, "status": TaskStatus.PENDING, "description": description}


def _register_task_action_routes(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register task action (kill/pause/resume) routes."""
    from fastapi import HTTPException

    @app.post("/api/tasks/{task_id}/kill")  # type: ignore[untyped-decorator]
    async def kill_task(task_id: str) -> dict[str, str]:
        """Kill a running task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.KILLED)
        await storage.log_audit("task_killed", details=f"task_id={task_id}")
        return {"id": task_id, "action": TaskStatus.KILLED}

    @app.post("/api/tasks/{task_id}/pause")  # type: ignore[untyped-decorator]
    async def pause_task(task_id: str) -> dict[str, str]:
        """Pause a running task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.PAUSED)
        await storage.log_audit("task_paused", details=f"task_id={task_id}")
        return {"id": task_id, "action": TaskStatus.PAUSED}

    @app.post("/api/tasks/{task_id}/resume")  # type: ignore[untyped-decorator]
    async def resume_task(task_id: str) -> dict[str, str]:
        """Resume a paused task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        await storage.update_task(task_id, status=TaskStatus.RUNNING)
        await storage.log_audit("task_resumed", details=f"task_id={task_id}")
        return {"id": task_id, "action": "resumed"}


def _register_agent_routes(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register agent-related API routes."""

    @app.get("/api/agents")  # type: ignore[untyped-decorator]
    async def list_agents() -> list[dict[str, Any]]:
        """List all registered agents."""
        storage = get_storage()
        return await storage.list_agents()


def _register_config_routes(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register config, blocks, teams, learnings, and audit API routes."""
    _register_status_routes(app, get_storage, guild_dir)
    _register_config_crud_routes(app, guild_dir)


def _register_status_routes(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register status, learnings, and audit routes."""
    _register_status_endpoint(app, get_storage)
    _register_blocks_endpoint(app)
    _register_teams_endpoints(app, guild_dir)
    _register_learnings_endpoint(app, get_storage)
    _register_audit_endpoint(app, get_storage)


def _register_status_endpoint(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register the GET /api/status route."""

    @app.get("/api/status")  # type: ignore[untyped-decorator]
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


def _register_blocks_endpoint(app: Any) -> None:
    """Register the GET /api/blocks route."""

    @app.get("/api/blocks")  # type: ignore[untyped-decorator]
    async def list_blocks() -> list[dict[str, str]]:
        """List available block definitions."""
        try:
            from guild.blocks.registry import BlockRegistry

            registry = BlockRegistry()
            return [{"name": block.name} for block in registry.list_blocks()]
        except (ImportError, OSError):
            return []


def _register_teams_endpoints(app: Any, guild_dir: Path) -> None:
    """Register the GET/POST /api/teams routes."""
    from fastapi import Request

    @app.get("/api/teams")  # type: ignore[untyped-decorator]
    async def list_teams() -> list[dict[str, str]]:
        """List configured team compositions."""
        try:
            from guild.config.loader import load_config

            config = load_config(guild_dir)
            return [{"name": t.name} for t in (config.teams or [])]
        except (ImportError, OSError, AttributeError):
            return []

    @app.post("/api/teams")  # type: ignore[untyped-decorator]
    async def save_team(request: Request) -> dict[str, str]:
        """Save a team composition from the visual composer (REQ-05.6)."""
        from fastapi import HTTPException

        from guild.config.loader import write_toml_bytes

        body = await request.json()
        name: str = body.get("name", "")
        if not name:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="Team name is required")
        teams_dir = guild_dir / "teams"
        teams_dir.mkdir(exist_ok=True)
        team_path = teams_dir / f"{name}.toml"
        blocks: dict[str, str] = body.get("blocks", {})
        connections: list[dict[str, str]] = body.get("connections", [])
        team_data: dict[str, Any] = {
            "team": {"name": name, "entry_block": next(iter(blocks), "")},
            "blocks": blocks,
            "connections": connections,
        }
        with open(team_path, "wb") as f:
            write_toml_bytes(f, team_data)
        return {"status": "ok", "name": name}


def _register_learnings_endpoint(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register the GET /api/learnings route."""

    @app.get("/api/learnings")  # type: ignore[untyped-decorator]
    async def list_learnings() -> list[dict[str, Any]]:
        """List all stored learnings."""
        storage = get_storage()
        return await storage.list_learnings()


def _register_audit_endpoint(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register the GET /api/audit route."""

    @app.get("/api/audit")  # type: ignore[untyped-decorator]
    async def get_audit(limit: int = 50) -> list[dict[str, Any]]:
        """Return recent audit log entries."""
        storage = get_storage()
        return await storage.list_audit(limit=limit)


def _register_config_crud_routes(app: Any, guild_dir: Path) -> None:
    """Register config GET/POST routes."""
    from fastapi import Request

    from guild.config.loader import load_config

    @app.get("/api/config")  # type: ignore[untyped-decorator]
    async def get_config() -> dict[str, Any]:
        """Return the current Guild configuration."""
        try:
            config = load_config(guild_dir)
            return config.model_dump() if hasattr(config, "model_dump") else {}
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load config: %s", exc)
            return {}

    @app.post("/api/config")  # type: ignore[untyped-decorator]
    async def post_config(request: Request) -> dict[str, str]:
        """Update Guild configuration (not yet implemented)."""
        await request.json()
        return {"status": "ok", "message": "Config update not yet implemented"}


def _register_websocket(app: Any, get_storage: Callable[[], "Storage"]) -> None:
    """Register the WebSocket endpoint for real-time updates (REQ-05.5)."""
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/ws")  # type: ignore[untyped-decorator]
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Send status updates every 2 seconds to connected clients."""
        await websocket.accept()
        try:
            while True:
                storage = get_storage()
                data = await _get_current_status(storage)
                await websocket.send_json(data)
                await asyncio.sleep(WEBSOCKET_POLL_SECONDS)
        except WebSocketDisconnect:
            pass
        except (ConnectionError, OSError, RuntimeError):
            logger.debug("WebSocket closed unexpectedly", exc_info=True)


def _register_static_files(app: Any) -> None:
    """Register static file serving for the built Svelte UI."""
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    if _UI_DIST.is_dir():
        app.mount(
            "/_app",
            StaticFiles(directory=str(_UI_DIST / "_app")),
            name="svelte-app",
        )

        @app.get("/{path:path}")  # type: ignore[untyped-decorator]
        async def serve_spa(path: str) -> FileResponse:
            """Serve the SPA — return index.html for all non-API routes."""
            file_path = _UI_DIST / path
            if file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(_UI_DIST / "index.html"))


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def _register_a2a_routes(app: Any) -> None:
    """Register A2A protocol routes (REQ-04.7a)."""
    from fastapi import Request

    # In-memory A2A task store (keyed by task ID)
    a2a_tasks: dict[str, dict[str, Any]] = {}

    @app.get("/.well-known/agent.json")  # type: ignore[untyped-decorator]
    async def agent_card() -> dict[str, Any]:
        """Return the A2A agent card for discovery."""
        return {
            "name": "Guild",
            "description": "Autonomous coding agent harness",
            "url": "/a2a",
            "version": __version__,
            "capabilities": {
                "methods": ["tasks/send", "tasks/get", "tasks/cancel"],
            },
        }

    @app.post("/a2a")  # type: ignore[untyped-decorator]
    async def a2a_endpoint(request: Request) -> dict[str, Any]:
        """JSON-RPC 2.0 dispatcher for A2A protocol."""
        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return _jsonrpc_error(None, JSONRPC_PARSE_ERROR, "Parse error")

        method = body.get("method")
        if not method:
            return _jsonrpc_error(body.get("id"), JSONRPC_INVALID_REQUEST, "Invalid request: missing method")

        req_id = body.get("id")
        params: dict[str, Any] = body.get("params", {})
        return _dispatch_a2a_method(method, req_id, params, a2a_tasks)


def _dispatch_a2a_method(
    method: str,
    req_id: Any,
    params: dict[str, Any],
    a2a_tasks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch an A2A JSON-RPC method to the appropriate handler."""
    if method == "tasks/send":
        return _a2a_tasks_send(req_id, params, a2a_tasks)
    elif method == "tasks/get":
        return _a2a_tasks_get(req_id, params, a2a_tasks)
    elif method == "tasks/cancel":
        return _a2a_tasks_cancel(req_id, params, a2a_tasks)
    else:
        return _jsonrpc_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")


def _a2a_tasks_send(
    req_id: Any, params: dict[str, Any], a2a_tasks: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Handle A2A tasks/send method."""
    import uuid

    message = params.get("message")
    if not message:
        return _jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "Invalid params: missing message")
    task_id = str(uuid.uuid4())
    a2a_tasks[task_id] = {
        "id": task_id,
        "status": {"state": "submitted"},
        "message": message,
    }
    return _jsonrpc_result(req_id, {"id": task_id, "status": {"state": "submitted"}})


def _a2a_tasks_get(
    req_id: Any, params: dict[str, Any], a2a_tasks: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Handle A2A tasks/get method."""
    task_id = params.get("id", "")
    task = a2a_tasks.get(task_id)
    if task is None:
        return _jsonrpc_error(req_id, JSONRPC_INTERNAL_ERROR, "Task not found")
    return _jsonrpc_result(req_id, {"id": task["id"], "status": task["status"]})


def _a2a_tasks_cancel(
    req_id: Any, params: dict[str, Any], a2a_tasks: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Handle A2A tasks/cancel method."""
    task_id = params.get("id", "")
    task = a2a_tasks.get(task_id)
    if task is None:
        return _jsonrpc_error(req_id, JSONRPC_INTERNAL_ERROR, "Task not found")
    task["status"] = {"state": "canceled"}
    return _jsonrpc_result(req_id, {"id": task["id"], "status": task["status"]})


def _build_lifespan(
    guild_dir: Path, db_path: Path, injected_storage: "Storage | None"
) -> Callable[..., Any]:
    """Build the FastAPI lifespan context manager."""
    from guild.storage.sqlite import Storage

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncGenerator[None, None]:
        """Manage Storage lifecycle: connect on startup, close on shutdown."""
        if injected_storage is not None:  # pragma: no cover — injected storage path for testing
            app.state.storage = injected_storage
            app.state.guild_dir = guild_dir
            logger.debug("API using injected storage for %s", guild_dir)
            yield
            return
        store = Storage(db_path)
        await store.connect()
        try:
            app.state.storage = store
            app.state.guild_dir = guild_dir
            logger.debug("API storage connected: %s", db_path)
            yield
        finally:
            await store.close()
            logger.debug("API storage closed for %s", db_path)

    return lifespan


def _register_all_routes(app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path) -> None:
    """Register all API routes on the app."""
    _register_a2a_routes(app)
    _register_task_routes(app, get_storage)
    _register_agent_routes(app, get_storage)
    _register_config_routes(app, get_storage, guild_dir)
    _register_websocket(app, get_storage)
    _register_static_files(app)


def create_app(
    guild_dir: Path | None = None,
    storage: "Storage | None" = None,
) -> Any:
    """Create the FastAPI app. Raises ImportError if fastapi not installed.

    Args:
        guild_dir: Path to .guild/ directory for accessing Storage.
                   If None, uses .guild/ in current working directory.
        storage: Optional pre-connected Storage instance (for testing).
                 When provided, the lifespan will not create/close storage.
    """
    try:
        from fastapi import FastAPI
    except ImportError as exc:
        raise ImportError("Install fastapi for API support: pip install guild[api]") from exc

    from guild.config.loader import find_guild_dir
    from guild.storage.sqlite import Storage

    _guild_dir = guild_dir or find_guild_dir() or Path.cwd() / GUILD_DIR_NAME
    _db_path = _guild_dir / DB_FILENAME

    lifespan = _build_lifespan(_guild_dir, _db_path, storage)
    app = FastAPI(title="Guild", version=__version__, lifespan=lifespan)

    def _get_storage() -> Storage:
        """Retrieve Storage from app state."""
        return app.state.storage  # type: ignore[no-any-return]

    _register_all_routes(app, _get_storage, _guild_dir)

    return app
