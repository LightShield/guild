"""REST API server — requires fastapi + uvicorn (REQ-05.4, REQ-05.5).

Serves the Guild web UI (static files from ui/dist/) and provides JSON API
routes backed by Storage for tasks, agents, config, audit, and learnings.
Includes WebSocket endpoint for real-time status updates.
"""

import asyncio
import json
import math
import os
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from logger_python import get_logger

if TYPE_CHECKING:
    from guild.storage.sqlite import Storage

from guild import __version__
from guild.config.constants import (
    DEFAULT_QUERY_LIMIT,
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

_SAFE_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")

API_ROUTES: dict[str, str] = {
    "GET /api/status": "Project status, tasks, agents",
    "GET /api/tasks": "List all tasks",
    "GET /api/tasks/{id}": "Get task details",
    "GET /api/tasks/{id}/messages": "Get task messages",
    "GET /api/tasks/{id}/events": "Get task timeline events",
    "GET /api/workflows": "List workflow executions",
    "GET /api/workflows/{execution_id}": "Get workflow execution details",
    "GET /api/agents": "List all agents",
    "GET /api/blocks": "List available blocks",
    "POST /api/blocks/{name}/run": "Run one block agent",
    "GET /api/teams": "List available teams",
    "POST /api/teams": "Save team composition",
    "POST /api/teams/{name}/run": "Run a saved team",
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


def _toml_quote(value: Any) -> str:
    """Return a TOML basic string literal."""
    text = str(value)
    return (
        '"'
        + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        + '"'
    )


def _toml_string_array(values: Any) -> str:
    """Return a TOML array containing basic string literals."""
    if not isinstance(values, list):
        from fastapi import HTTPException

        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="tools must be a list")
    return "[" + ", ".join(_toml_quote(value) for value in values) + "]"


def _validate_toml_key(value: Any, label: str) -> str:
    """Validate path-derived identifiers before using them as filenames or TOML keys."""
    if not isinstance(value, str) or not value or not _SAFE_TOML_KEY_RE.fullmatch(value):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=HTTP_BAD_REQUEST,
            detail=f"{label} must contain only letters, numbers, underscores, and hyphens",
        )
    return value


def _toml_number(value: Any, label: str) -> str:
    """Validate and serialize a finite TOML number."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        from fastapi import HTTPException

        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail=f"{label} must be a number")
    return str(value)


def _toml_position_attrs(position: Any) -> list[str]:
    """Validate and serialize UI position metadata."""
    if position is None:
        return []
    if not isinstance(position, dict) or "x" not in position or "y" not in position:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=HTTP_BAD_REQUEST,
            detail="position must include numeric x and y values",
        )
    return [
        f"x = {_toml_number(position['x'], 'position.x')}",
        f"y = {_toml_number(position['y'], 'position.y')}",
    ]


async def _get_current_status(storage: "Storage", guild_dir: Path) -> dict[str, Any]:
    """Gather current status for WebSocket broadcast."""
    await _mark_stale_tasks(storage, guild_dir)
    summary = await storage.get_token_summary()
    tasks = await storage.list_tasks()
    agents = await storage.list_agents()
    task_events = await storage.list_task_events(limit=150)
    return {
        "status": "ok",
        "version": __version__,
        "task_count": summary["task_count"],
        "agent_count": summary["agent_count"],
        "total_input_tokens": summary["total_input"],
        "total_output_tokens": summary["total_output"],
        "tasks": tasks,
        "agents": agents,
        "task_events": task_events,
    }


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


def _task_has_live_pid(guild_dir: Path, task_id: str) -> bool:
    """Return True when a daemon PID file exists and points at a live process."""
    pid_path = guild_dir / "run" / f"{task_id}.pid"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _looks_like_block_child_task(task: dict[str, Any]) -> bool:
    """Return True for per-block rows created inside a parent team run."""
    assigned_agent = str(task.get("assigned_agent") or "")
    description = str(task.get("description") or "")
    is_generated_agent = bool(re.match(r"^[A-Za-z0-9_-]+-[0-9a-f]{8}$", assigned_agent))
    return description.startswith("[") or is_generated_agent


def _is_workflow_task(task: dict[str, Any], events: list[dict[str, Any]] | None = None) -> bool:
    """Return True for top-level workflow execution tasks."""
    assigned_agent = str(task.get("assigned_agent") or "")
    if not assigned_agent or assigned_agent == "agent":
        return False
    if _looks_like_block_child_task(task):
        return False
    if "Completed blocks:" in str(task.get("result") or ""):
        return True
    return any(
        event.get("task_id") == task.get("task_id")
        and str(event.get("event_type") or "").startswith("block_")
        for event in events or []
    )


def _workflow_output(task: dict[str, Any]) -> str:
    """Extract the latest workflow artifact from a progress/result string."""
    result = str(task.get("result") or "")
    marker = "Latest output:\n"
    if marker in result:
        return result.split(marker, 1)[1].strip()
    return result.strip()


def _workflow_record(
    task: dict[str, Any],
    events: list[dict[str, Any]],
    all_tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a workflow execution record for API/UI consumers."""
    execution_id = str(task["task_id"])
    child_agents = [
        str(event["agent_id"])
        for event in events
        if event.get("event_type") == "agent_spawned" and event.get("agent_id")
    ]
    child_tasks = [
        {
            **child,
            "execution_id": execution_id,
        }
        for child in all_tasks
        if child.get("assigned_agent") in child_agents
    ]
    return {
        **task,
        "execution_id": execution_id,
        "workflow_name": task.get("assigned_agent"),
        "output": _workflow_output(task),
        "events": events,
        "child_tasks": child_tasks,
    }


def _task_is_older_than(task: dict[str, Any], seconds: int) -> bool:
    """Return True when a task was created more than seconds ago."""
    try:
        created = datetime.fromisoformat(str(task.get("created_at") or ""))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > timedelta(seconds=seconds)


async def _mark_stale_tasks(storage: "Storage", guild_dir: Path) -> None:
    """Mark orphaned parent and child tasks failed so the UI does not show phantom runs."""
    running_tasks = await storage.list_tasks(status=TaskStatus.RUNNING)
    all_tasks = {task["task_id"]: task for task in await storage.list_tasks()}
    parent_by_agent: dict[str, str] = {}
    for event in await storage.list_task_events(limit=1000):
        if event.get("event_type") != "agent_spawned" or not event.get("agent_id"):
            continue
        parent_by_agent[str(event["agent_id"])] = str(event["task_id"])

    for task in running_tasks:
        task_id = task.get("task_id", "")
        if _looks_like_block_child_task(task):
            parent_id = parent_by_agent.get(str(task.get("assigned_agent") or ""))
            parent = all_tasks.get(parent_id or "")
            if parent is None:
                if _task_is_older_than(task, 30):
                    message = "Stopped: block task has no linked parent workflow."
                    await storage.update_task(
                        task_id,
                        status=TaskStatus.FAILED,
                        completed_at=_now(),
                        result=message,
                    )
                    await storage.add_task_event(
                        task_id,
                        "failed",
                        message,
                        agent_id=task.get("assigned_agent"),
                    )
                continue
            parent_status = str(parent.get("status") or "")
            parent_running_without_pid = (
                parent_status == TaskStatus.RUNNING
                and not _task_has_live_pid(guild_dir, str(parent.get("task_id") or ""))
            )
            if parent_status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.KILLED,
            } or parent_running_without_pid:
                message = "Stopped: parent workflow is no longer running."
                await storage.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    completed_at=_now(),
                    result=message,
                )
                await storage.add_task_event(
                    task_id,
                    "failed",
                    message,
                    agent_id=task.get("assigned_agent"),
                )
            continue
        if _task_has_live_pid(guild_dir, task_id):
            continue
        message = "Stopped: no live daemon process owns this running task."
        await storage.update_task(
            task_id,
            status=TaskStatus.FAILED,
            completed_at=_now(),
            result=message,
        )
        await storage.add_task_event(
            task_id,
            "failed",
            message,
            agent_id=task.get("assigned_agent"),
        )


def _register_task_routes(app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path) -> None:
    """Register task-related API routes."""
    _register_task_query_routes(app, get_storage, guild_dir)
    _register_task_action_routes(app, get_storage, guild_dir)


def _register_task_query_routes(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register task query (GET/POST create) routes."""
    from fastapi import HTTPException, Request

    @app.get("/api/tasks")  # type: ignore[untyped-decorator]
    async def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        storage = get_storage()
        await _mark_stale_tasks(storage, guild_dir)
        return await storage.list_tasks(status=status)

    @app.get("/api/tasks/{task_id}")  # type: ignore[untyped-decorator]
    async def get_task(task_id: str) -> dict[str, Any]:
        """Return a single task by ID."""
        storage = get_storage()
        await _mark_stale_tasks(storage, guild_dir)
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
        await storage.add_task_event(
            task_id,
            "queued",
            "Task created from the UI; waiting for daemon startup.",
        )
        await storage.log_audit("task_created", details=f"task_id={task_id}")
        from guild.cli.daemon_ops import launch_background_task

        launch_background_task(guild_dir, task_id)
        return {"id": task_id, "status": TaskStatus.PENDING, "description": description}

    @app.get("/api/tasks/{task_id}/events")  # type: ignore[untyped-decorator]
    async def get_task_events(task_id: str) -> list[dict[str, Any]]:
        """Return timeline events for a task."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        return await storage.list_task_events(task_id)


    @app.get("/api/tasks/{task_id}/messages")  # type: ignore[untyped-decorator]
    async def get_task_messages(task_id: str) -> dict[str, Any]:
        """Return messages for the task's assigned agent."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        agent_id = task.get("assigned_agent")
        messages = await storage.get_messages(agent_id) if agent_id else []
        return {"task": task, "agent_id": agent_id, "messages": messages}


def _register_task_action_routes(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register task action (kill/pause/resume) routes."""
    from fastapi import HTTPException

    @app.post("/api/tasks/{task_id}/kill")  # type: ignore[untyped-decorator]
    async def kill_task(task_id: str) -> dict[str, str]:
        """Kill a running task by ID."""
        storage = get_storage()
        task = await storage.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Task not found")
        from guild.cli.daemon_ops import kill_task as kill_daemon_task

        killed = (
            kill_daemon_task(task_id, guild_dir)
            if _task_has_live_pid(guild_dir, task_id)
            else False
        )
        await storage.update_task(
            task_id,
            status=TaskStatus.KILLED,
            completed_at=_now(),
            result="Killed by user." if killed else "Stopped: no live process was found.",
        )
        await storage.add_task_event(
            task_id,
            "killed",
            "Stop requested from the UI."
            if killed
            else "Stop requested from the UI; no live process was found.",
        )
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
        agents = await storage.list_agents()
        tasks = await storage.list_tasks()
        tasks_by_id = {task["task_id"]: task for task in tasks}
        tasks_by_agent = {
            task.get("assigned_agent"): task for task in tasks if task.get("assigned_agent")
        }
        events = await storage.list_task_events(limit=300)
        parent_by_agent: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.get("event_type") != "agent_spawned":
                continue
            agent_id = event.get("agent_id")
            task_id = event.get("task_id")
            if agent_id and task_id and task_id in tasks_by_id:
                parent_by_agent[str(agent_id)] = tasks_by_id[str(task_id)]

        enriched = []
        for agent in agents:
            agent_task = tasks_by_id.get(agent.get("task_id")) or tasks_by_agent.get(
                agent.get("agent_id")
            )
            parent_task = parent_by_agent.get(str(agent.get("agent_id")))
            enriched.append(
                {
                    **agent,
                    "task": agent_task,
                    "parent_task": parent_task,
                }
            )
        return enriched


def _register_workflow_routes(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register workflow execution query routes."""
    from fastapi import HTTPException

    @app.get("/api/workflows")  # type: ignore[untyped-decorator]
    async def list_workflows(status: str | None = None) -> list[dict[str, Any]]:
        """List workflow executions with stable execution IDs."""
        storage = get_storage()
        await _mark_stale_tasks(storage, guild_dir)
        tasks = await storage.list_tasks()
        events = await storage.list_task_events(limit=1000)
        workflow_tasks = [task for task in tasks if _is_workflow_task(task, events)]
        if status:
            workflow_tasks = [task for task in workflow_tasks if task.get("status") == status]
        records = []
        for task in workflow_tasks:
            task_events = [event for event in events if event.get("task_id") == task["task_id"]]
            records.append(_workflow_record(task, task_events, tasks))
        return sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    @app.get("/api/workflows/{execution_id}")  # type: ignore[untyped-decorator]
    async def get_workflow(execution_id: str) -> dict[str, Any]:
        """Return one workflow execution by execution ID."""
        storage = get_storage()
        await _mark_stale_tasks(storage, guild_dir)
        task = await storage.get_task(execution_id)
        if task is None:
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Workflow execution not found")
        task_events = await storage.list_task_events(execution_id)
        all_events = await storage.list_task_events(limit=2000)
        all_tasks = await storage.list_tasks()
        if not _is_workflow_task(task, all_events):
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail="Workflow execution not found")
        record = _workflow_record(task, task_events, all_tasks)
        child_agents = {child["assigned_agent"] for child in record["child_tasks"]}
        record["child_events"] = [
            event for event in all_events if event.get("agent_id") in child_agents
        ]
        return record


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
    _register_status_endpoint(app, get_storage, guild_dir)
    _register_blocks_endpoint(app, guild_dir)
    _register_teams_endpoints(app, guild_dir)
    _register_learnings_endpoint(app, get_storage)
    _register_audit_endpoint(app, get_storage)


def _register_status_endpoint(
    app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path
) -> None:
    """Register the GET /api/status route."""

    @app.get("/api/status")  # type: ignore[untyped-decorator]
    async def get_status() -> dict[str, Any]:
        """Return project status with token usage summaries."""
        storage = get_storage()
        await _mark_stale_tasks(storage, guild_dir)
        summary = await storage.get_token_summary()
        return {
            "status": "ok",
            "version": __version__,
            "task_count": summary["task_count"],
            "agent_count": summary["agent_count"],
            "total_input_tokens": summary["total_input"],
            "total_output_tokens": summary["total_output"],
        }


def _register_blocks_endpoint(app: Any, guild_dir: Path) -> None:
    """Register the GET /api/blocks route."""
    from fastapi import Request

    @app.get("/api/blocks")  # type: ignore[untyped-decorator]
    async def list_blocks() -> list[dict[str, Any]]:
        """List available block definitions with full detail."""
        try:
            from guild.blocks.registry import BlockRegistry

            registry = BlockRegistry()
            registry.load_from_dir(guild_dir / "blocks")
            results = []
            for block in registry.list_blocks():
                results.append(
                    {
                        "name": block.name,
                        "role": block.role,
                        "version": block.version,
                        "system_prompt": block.system_prompt,
                        "provider": block.provider,
                        "model": block.model,
                        "tools": block.tools,
                        "max_retries": block.max_retries,
                        "inputs": [{"name": p.name, "type_tag": p.type_tag} for p in block.inputs],
                        "outputs": [
                            {"name": p.name, "type_tag": p.type_tag} for p in block.outputs
                        ],
                    }
                )
            return results
        except (ImportError, OSError):
            return []

    @app.get("/api/blocks/{block_name}")  # type: ignore[untyped-decorator]
    async def get_block(block_name: str) -> dict[str, Any]:
        """Get a single block definition by name."""
        from fastapi import HTTPException

        from guild.blocks.registry import BlockRegistry

        block_name = _validate_toml_key(block_name, "Block name")
        registry = BlockRegistry()
        registry.load_from_dir(guild_dir / "blocks")
        block = registry.get_block(block_name)
        if block is None:
            raise HTTPException(
                status_code=HTTP_NOT_FOUND, detail=f"Block '{block_name}' not found"
            )
        return {
            "name": block.name,
            "role": block.role,
            "version": block.version,
            "system_prompt": block.system_prompt,
            "provider": block.provider,
            "model": block.model,
            "tools": block.tools,
            "max_retries": block.max_retries,
            "inputs": [
                {"name": p.name, "type_tag": p.type_tag, "description": p.description}
                for p in block.inputs
            ],
            "outputs": [
                {"name": p.name, "type_tag": p.type_tag, "description": p.description}
                for p in block.outputs
            ],
        }

    @app.post("/api/blocks/{block_name}/run")  # type: ignore[untyped-decorator]
    async def run_block(block_name: str, request: Request) -> dict[str, Any]:
        """Create a task and run it through one selected block agent."""
        import uuid

        from fastapi import HTTPException

        from guild.blocks.registry import BlockRegistry

        block_name = _validate_toml_key(block_name, "Block name")
        registry = BlockRegistry()
        registry.load_from_dir(guild_dir / "blocks")
        if registry.get_block(block_name) is None:
            raise HTTPException(
                status_code=HTTP_NOT_FOUND, detail=f"Block '{block_name}' not found"
            )

        body = await request.json()
        description: str = body.get("description", "").strip()
        if not description:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="description is required")

        task_id = str(uuid.uuid4())
        db_path = guild_dir / DB_FILENAME
        from guild.storage.sqlite import Storage

        async with Storage(db_path) as store:
            await store.create_task(task_id, description)
            await store.add_task_event(
                task_id,
                "queued",
                f"Agent '{block_name}' queued from Tasks; waiting for daemon startup.",
            )
            await store.update_task(
                task_id,
                assigned_agent=block_name,
                result=f"Queued agent '{block_name}'...",
            )
            await store.log_audit(
                "block_task_created",
                details=f"task_id={task_id} block={block_name}",
            )

        from guild.cli.daemon_ops import launch_background_block_task

        launch_background_block_task(guild_dir, task_id, block_name)
        return {
            "id": task_id,
            "status": TaskStatus.PENDING,
            "description": description,
            "agent": block_name,
        }

    @app.post("/api/blocks")  # type: ignore[untyped-decorator]
    async def create_block(request: Request) -> dict[str, str]:
        """Create a new block definition (writes TOML to .guild/blocks/)."""
        from fastapi import HTTPException

        body = await request.json()
        name: str = body.get("name", "")
        if not name:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="Block name is required")
        name = _validate_toml_key(name, "Block name")

        blocks_dir = guild_dir / "blocks"
        blocks_dir.mkdir(exist_ok=True)
        block_path = blocks_dir / f"{name}.toml"

        role: str = body.get("role", "agent")
        provider: str = body.get("provider", "")
        model: str = body.get("model", "")
        system_prompt: str = body.get("system_prompt", body.get("instructions", ""))
        tools: list[str] = body.get("tools", [])
        max_retries = body.get("max_retries", 1)
        inputs: list[dict[str, str]] = body.get("inputs", [{"name": "input", "type_tag": "any"}])
        outputs: list[dict[str, str]] = body.get("outputs", [{"name": "output", "type_tag": "any"}])

        lines = [
            "[block]",
            f"name = {_toml_quote(name)}",
            f"role = {_toml_quote(role)}",
            'version = "1.0.0"',
            f"system_prompt = {_toml_quote(system_prompt)}",
            f"max_retries = {_toml_number(max_retries, 'max_retries')}",
        ]
        if provider:
            lines.append(f"provider = {_toml_quote(provider)}")
        if model:
            lines.append(f"model = {_toml_quote(model)}")
        lines.append(f"tools = {_toml_string_array(tools)}")

        for port in inputs:
            lines.append("")
            lines.append("[[block.inputs]]")
            lines.append(f"name = {_toml_quote(port.get('name', 'input'))}")
            lines.append(f"type = {_toml_quote(port.get('type_tag', port.get('type', 'any')))}")

        for port in outputs:
            lines.append("")
            lines.append("[[block.outputs]]")
            lines.append(f"name = {_toml_quote(port.get('name', 'output'))}")
            lines.append(f"type = {_toml_quote(port.get('type_tag', port.get('type', 'any')))}")

        # Composite block: store children and internal edges
        children: list[dict[str, Any]] = body.get("children", [])
        internal_edges: list[dict[str, str]] = body.get("internal_edges", [])
        if children:
            lines.append("")
            lines.append("[block.composition]")
            entry_child = _validate_toml_key(
                children[0].get("name", children[0].get("id", "")), "Entry child"
            )
            lines.append(f"entry_block = {_toml_quote(entry_child)}")
            lines.append("")
            lines.append("[block.composition.blocks]")
            for child in children:
                child_name = _validate_toml_key(
                    child.get("name", child.get("id", "")), "Child name"
                )
                child_type = _validate_toml_key(
                    child.get("type", child.get("role", "agent")), "Child type"
                )
                lines.append(f"{child_name} = {_toml_quote(child_type)}")
            for edge in internal_edges:
                lines.append("")
                lines.append("[[block.composition.connections]]")
                source_block = _validate_toml_key(edge.get("sourceChildId", ""), "Source child")
                target_block = _validate_toml_key(edge.get("targetChildId", ""), "Target child")
                lines.append(f"source_block = {_toml_quote(source_block)}")
                lines.append(f"source_port = {_toml_quote(edge.get('sourcePortId', 'output'))}")
                lines.append(f"target_block = {_toml_quote(target_block)}")
                lines.append(f"target_port = {_toml_quote(edge.get('targetPortId', 'input'))}")

        lines.append("")
        block_path.write_text("\n".join(lines))
        return {"status": "ok", "name": name}

    @app.delete("/api/blocks/{block_name}")  # type: ignore[untyped-decorator]
    async def delete_block(block_name: str) -> dict[str, str]:
        """Delete a block definition."""
        from fastapi import HTTPException

        block_name = _validate_toml_key(block_name, "Block name")
        block_path = guild_dir / "blocks" / f"{block_name}.toml"
        if not block_path.exists():
            raise HTTPException(
                status_code=HTTP_NOT_FOUND, detail=f"Block '{block_name}' not found"
            )
        block_path.unlink()
        return {"status": "ok", "name": block_name}


def _register_teams_endpoints(app: Any, guild_dir: Path) -> None:
    """Register the GET/POST /api/teams routes."""
    from fastapi import Request

    @app.get("/api/teams")  # type: ignore[untyped-decorator]
    async def list_teams() -> list[dict[str, str]]:
        """List configured team compositions from .guild/teams/*.toml."""
        results = []
        teams_dir = guild_dir / "teams"
        if teams_dir.is_dir():
            for f in sorted(teams_dir.glob("*.toml")):
                results.append({"name": f.stem})
        if not results:
            try:
                from guild.config.loader import load_config

                config = load_config(guild_dir)
                teams = getattr(config, "teams", None) or []
                results = [{"name": t.name} for t in teams]
            except (ImportError, OSError, AttributeError):
                pass
        return results

    @app.get("/api/teams/{team_name}")  # type: ignore[untyped-decorator]
    async def get_team(team_name: str) -> dict[str, Any]:
        """Get a team definition by name (reads TOML)."""
        from fastapi import HTTPException

        team_name = _validate_toml_key(team_name, "Team name")
        team_path = guild_dir / "teams" / f"{team_name}.toml"
        if not team_path.exists():
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail=f"Team '{team_name}' not found")
        content = team_path.read_text()
        try:
            import tomllib

            data = tomllib.loads(content)
        except (ImportError, ValueError):
            try:
                import tomli as tomllib  # type: ignore[import-not-found,no-redef]

                data = tomllib.loads(content)
            except (ImportError, ValueError):
                return {"name": team_name, "raw": content}
        team = data.get("team", {})
        blocks = team.get("blocks", {})
        ui = team.get("ui", {})
        if isinstance(blocks, dict) and isinstance(ui, dict):
            normalized_ui = {}
            for key, value in ui.items():
                if isinstance(value, dict) and "x" in value and "y" in value:
                    value = {
                        **value,
                        "position": {"x": value.pop("x"), "y": value.pop("y")},
                    }
                normalized_ui[key] = value
            ui = normalized_ui
            blocks = {
                key: {**value, "type": blocks.get(key, key)}
                if isinstance(value, dict)
                else blocks.get(key, key)
                for key, value in ui.items()
            } | {key: value for key, value in blocks.items() if key not in ui}
        return {
            "name": team.get("name", team_name),
            "description": team.get("description", ""),
            "entry_block": team.get("entry_block", ""),
            "blocks": blocks,
            "connections": team.get("connections", []),
            "ui": ui,
        }

    @app.delete("/api/teams/{team_name}")  # type: ignore[untyped-decorator]
    async def delete_team(team_name: str) -> dict[str, str]:
        """Delete a team definition."""
        from fastapi import HTTPException

        team_name = _validate_toml_key(team_name, "Team name")
        team_path = guild_dir / "teams" / f"{team_name}.toml"
        if not team_path.exists():
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail=f"Team '{team_name}' not found")
        team_path.unlink()
        return {"status": "ok", "name": team_name}

    @app.post("/api/teams/{team_name}/run")  # type: ignore[untyped-decorator]
    async def run_team(team_name: str, request: Request) -> dict[str, Any]:
        """Create a task and run it through a saved team composition."""
        import uuid

        from fastapi import HTTPException

        team_name = _validate_toml_key(team_name, "Team name")
        team_path = guild_dir / "teams" / f"{team_name}.toml"
        if not team_path.exists():
            raise HTTPException(status_code=HTTP_NOT_FOUND, detail=f"Team '{team_name}' not found")

        body = await request.json()
        description: str = body.get("description", "").strip()
        if not description:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="description is required")

        task_id = str(uuid.uuid4())
        db_path = guild_dir / DB_FILENAME
        from guild.storage.sqlite import Storage

        async with Storage(db_path) as store:
            await store.create_task(task_id, description)
            await store.add_task_event(
                task_id,
                "queued",
                f"Flow '{team_name}' queued from Composer; waiting for daemon startup.",
            )
            await store.update_task(
                task_id,
                assigned_agent=team_name,
                result=f"Queued flow '{team_name}'...",
            )
            await store.log_audit(
                "team_task_created",
                details=f"task_id={task_id} team={team_name}",
            )

        from guild.cli.daemon_ops import launch_background_team_task

        launch_background_team_task(guild_dir, task_id, team_name)
        return {
            "id": task_id,
            "status": TaskStatus.PENDING,
            "description": description,
            "team": team_name,
        }

    @app.post("/api/teams")  # type: ignore[untyped-decorator]
    async def save_team(request: Request) -> dict[str, str]:
        """Save a team composition from the visual composer (REQ-05.6)."""
        from fastapi import HTTPException

        body = await request.json()
        name: str = body.get("name", "")
        if not name:
            raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="Team name is required")
        name = _validate_toml_key(name, "Team name")
        teams_dir = guild_dir / "teams"
        blocks_dir = guild_dir / "blocks"
        teams_dir.mkdir(exist_ok=True)
        blocks_dir.mkdir(exist_ok=True)
        team_path = teams_dir / f"{name}.toml"
        blocks: dict[str, Any] = body.get("blocks", {})
        raw_connections: list[dict[str, str]] = body.get("connections", [])
        connections: list[dict[str, str]] = []
        seen_connections: set[tuple[str, str, str, str]] = set()
        for conn in raw_connections:
            key = (
                str(conn.get("source_block", "")),
                str(conn.get("source_port", "output")),
                str(conn.get("target_block", "")),
                str(conn.get("target_port", "input")),
            )
            if key in seen_connections:
                continue
            seen_connections.add(key)
            connections.append(conn)
        description: str = body.get("description", "")
        entry_block: str = body.get("entry_block", next(iter(blocks), ""))
        if entry_block:
            entry_block = _validate_toml_key(entry_block, "Entry block")

        lines = [
            "[team]",
            f"name = {_toml_quote(name)}",
            f"description = {_toml_quote(description)}",
            f"entry_block = {_toml_quote(entry_block)}",
            "",
            "[team.blocks]",
        ]
        for key, val in blocks.items():
            key = _validate_toml_key(key, "Block key")
            if isinstance(val, dict):
                block_type = val.get("type", val.get("name", key))
                block_type = _validate_toml_key(str(block_type), "Block type")
                lines.append(f"{key} = {_toml_quote(block_type)}")
                block_lines = [
                    "[block]",
                    f"name = {_toml_quote(block_type)}",
                    f"role = {_toml_quote(val.get('role', 'agent'))}",
                    'version = "1.0.0"',
                    f"system_prompt = {_toml_quote(val.get('instructions', ''))}",
                ]
                if val.get("provider"):
                    block_lines.append(f"provider = {_toml_quote(val['provider'])}")
                if val.get("model"):
                    block_lines.append(f"model = {_toml_quote(val['model'])}")
                block_lines.extend(
                    [
                        'tools = ["file_read", "file_write", "shell", "search"]',
                        "",
                        "[[block.inputs]]",
                        'name = "in"',
                        'type = "any"',
                        "",
                        "[[block.outputs]]",
                        'name = "out"',
                        'type = "any"',
                        "",
                    ]
                )
                (blocks_dir / f"{block_type}.toml").write_text("\n".join(block_lines))
            else:
                block_type = _validate_toml_key(str(val), "Block type")
                lines.append(f"{key} = {_toml_quote(block_type)}")
        for conn in connections:
            lines.append("")
            lines.append("[[team.connections]]")
            source_block = _validate_toml_key(conn.get("source_block", ""), "Source block")
            target_block = _validate_toml_key(conn.get("target_block", ""), "Target block")
            lines.append(f"source_block = {_toml_quote(source_block)}")
            lines.append(f"source_port = {_toml_quote(conn.get('source_port', 'output'))}")
            lines.append(f"target_block = {_toml_quote(target_block)}")
            lines.append(f"target_port = {_toml_quote(conn.get('target_port', 'input'))}")

        # Store UI positions as metadata comment (not consumed by runtime)
        ui_nodes = {k: v for k, v in blocks.items() if isinstance(v, dict)}
        if ui_nodes:
            lines.append("")
            lines.append("# UI layout metadata (not used by runtime)")
            lines.append("[team.ui]")
            for key, val in ui_nodes.items():
                key = _validate_toml_key(key, "Block key")
                attrs = []
                attrs.extend(_toml_position_attrs(val.get("position")))
                for field in ("provider", "model", "role", "instructions", "name"):
                    if val.get(field):
                        attrs.append(f"{field} = {_toml_quote(val[field])}")
                if attrs:
                    lines.append(f'{key} = {{ {", ".join(attrs)} }}')

        lines.append("")
        team_path.write_text("\n".join(lines))
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
    async def get_audit(limit: int = DEFAULT_QUERY_LIMIT) -> list[dict[str, Any]]:
        """Return recent audit log entries."""
        storage = get_storage()
        return await storage.list_audit(limit=limit)


def _register_config_crud_routes(app: Any, guild_dir: Path) -> None:
    """Register config GET/POST routes."""
    from fastapi import Request

    from guild.config.loader import load_config, write_toml_bytes

    config_sections = {
        "provider": [
            "provider_name",
            "base_url",
            "model",
            "temperature",
            "max_tokens",
            "health_check_timeout_seconds",
        ],
        "guild": [
            "default_permission",
            "max_concurrent_agents",
            "max_concurrent_tool_calls",
            "autonomy_timeout_minutes",
            "stuck_max_repeated_errors",
            "stuck_max_no_progress_turns",
            "stuck_max_repeated_calls",
            "shell_timeout_seconds",
            "shell_max_output_chars",
            "cli_provider_timeout_seconds",
            "default_max_turns",
            "context_max_tokens",
            "compact_threshold",
            "preserve_recent_messages",
            "websocket_poll_seconds",
            "max_spawn_depth",
        ],
        "escalation": ["escalation_chain", "escalation_cli_providers"],
        "daemon": ["auto_recovery", "presence_aware_notifications"],
        "security": ["sandbox_mode", "sandbox_network"],
        "routing": ["permission_model"],
        "resource": ["resource_mode"],
    }

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
        """Update Guild configuration."""
        body = await request.json()
        config_path = guild_dir / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        nested: dict[str, dict[str, Any]] = {}
        for section, keys in config_sections.items():
            values = {key: body[key] for key in keys if key in body}
            if values:
                nested[section] = values
        with config_path.open("wb") as f:
            write_toml_bytes(f, nested)
        return {"status": "ok", "message": "Config saved"}


def _register_websocket(app: Any, get_storage: Callable[[], "Storage"], guild_dir: Path) -> None:
    """Register the WebSocket endpoint for real-time updates (REQ-05.5)."""
    from fastapi import WebSocket, WebSocketDisconnect

    @app.websocket("/ws")  # type: ignore[untyped-decorator]
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Send status updates every 2 seconds to connected clients."""
        await websocket.accept()
        try:
            while True:
                storage = get_storage()
                data = await _get_current_status(storage, guild_dir)
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
            return _jsonrpc_error(
                body.get("id"),
                JSONRPC_INVALID_REQUEST,
                "Invalid request: missing method",
            )

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
    _register_task_routes(app, get_storage, guild_dir)
    _register_agent_routes(app, get_storage)
    _register_workflow_routes(app, get_storage, guild_dir)
    _register_config_routes(app, get_storage, guild_dir)
    _register_websocket(app, get_storage, guild_dir)
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
