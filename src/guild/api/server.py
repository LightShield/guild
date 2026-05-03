"""Guild REST API — FastAPI backend serving the same data as the CLI.

Provides REST endpoints + WebSocket for real-time agent monitoring.
The GUI is a static SPA served from /gui/.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from guild.core.config import find_guild_dir, load_config
from guild.core.storage import Storage

__all__ = ["create_app"]

DB_NAME = "guild.db"


class TaskRequest(BaseModel):
    """Request body for creating a task."""

    description: str
    team: str | None = None
    permission: str = "ask"


class ConfigSetRequest(BaseModel):
    """Request body for setting a config value."""

    section: str
    key: str
    value: Any


# --- WebSocket manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._connections.remove(ws)

    async def broadcast(self, data: dict) -> None:
        """Send data to all connected clients."""
        for ws in list(self._connections):
            try:
                await ws.send_json(data)
            except Exception:
                self._connections.remove(ws)


ws_manager = ConnectionManager()


def _get_guild_dir() -> Path:
    """Find guild dir or raise 404."""
    gd = find_guild_dir()
    if not gd:
        raise HTTPException(404, "Not a Guild project. Run 'guild init' first.")
    return gd


async def _get_storage(guild_dir: Path) -> Storage:
    """Get a connected storage instance."""
    s = Storage(guild_dir / DB_NAME)
    await s.connect()
    return s


def create_app() -> FastAPI:
    """Create the FastAPI application.

    Returns:
        Configured FastAPI app with all routes.
    """
    app = FastAPI(title="Guild", version="0.1.0")

    # Serve static GUI files
    gui_dir = Path(__file__).parent.parent / "gui" / "static"
    if gui_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(gui_dir)), name="static")

    # --- Status ---

    @app.get("/api/status")
    async def get_status() -> dict:
        """Get project status: tasks, agents, learnings count."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            tasks = await s.list_tasks()
            agents = await s.list_agents()
            learnings = await s.list_learnings()
            return {
                "project": str(guild_dir.parent),
                "tasks": tasks,
                "agents": agents,
                "learnings_count": len(learnings),
            }
        finally:
            await s.close()

    # --- Tasks ---

    @app.get("/api/tasks")
    async def list_tasks(status: str | None = None) -> list[dict]:
        """List all tasks."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            return await s.list_tasks(status=status)
        finally:
            await s.close()

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        """Get a specific task."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            task = await s.get_task(task_id)
            if not task:
                raise HTTPException(404, f"Task {task_id} not found")
            return task
        finally:
            await s.close()

    # --- Agents ---

    @app.get("/api/agents")
    async def list_agents() -> list[dict]:
        """List all agents."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            return await s.list_agents()
        finally:
            await s.close()

    @app.get("/api/agents/{agent_id}/messages")
    async def get_agent_messages(agent_id: str) -> list[dict]:
        """Get messages for an agent."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            return await s.get_messages(agent_id)
        finally:
            await s.close()

    # --- Blocks & Teams ---

    @app.get("/api/blocks")
    async def list_blocks() -> list[dict]:
        """List available blocks."""
        from guild.blocks.registry import BlockRegistry

        guild_dir = find_guild_dir()
        registry = BlockRegistry()
        if guild_dir:
            registry.load_from_dir(guild_dir / "blocks")
        return [
            {
                "name": b.name, "role": b.role,
                "tools": b.tools,
                "inputs": [{"name": p.name, "type_tag": p.type_tag} for p in b.inputs],
                "outputs": [{"name": p.name, "type_tag": p.type_tag} for p in b.outputs],
            }
            for b in sorted(registry.blocks.values(), key=lambda x: x.name)
        ]

    @app.get("/api/teams")
    async def list_teams() -> list[dict]:
        """List available teams."""
        from guild.blocks.registry import BlockRegistry

        guild_dir = find_guild_dir()
        registry = BlockRegistry()
        if guild_dir:
            registry.load_from_dir(guild_dir / "blocks")
        return [
            {
                "name": t.name, "description": t.description,
                "blocks": t.blocks,
                "connections": [c.model_dump() for c in t.connections],
                "loops": [l.model_dump() for l in t.loops],
                "entry_block": t.entry_block,
            }
            for t in sorted(registry.teams.values(), key=lambda x: x.name)
        ]

    # --- Learnings ---

    @app.get("/api/learnings")
    async def list_learnings(min_confidence: float = 0.0) -> list[dict]:
        """List learnings."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            return await s.list_learnings(min_confidence=min_confidence)
        finally:
            await s.close()

    # --- Audit ---

    @app.get("/api/audit")
    async def list_audit(limit: int = 50) -> list[dict]:
        """List audit log entries."""
        guild_dir = _get_guild_dir()
        s = await _get_storage(guild_dir)
        try:
            return await s.list_audit(limit=limit)
        finally:
            await s.close()

    # --- Config ---

    @app.get("/api/config")
    async def get_config() -> dict:
        """Get current config."""
        guild_dir = _get_guild_dir()
        config = load_config(guild_dir)
        return config.model_dump()

    # --- WebSocket ---

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """WebSocket for real-time updates."""
        await ws_manager.connect(ws)
        try:
            while True:
                data = await ws.receive_text()
                # Echo for now; will be used for chat later
                await ws.send_json({"type": "ack", "data": data})
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    # --- GUI entry point ---

    @app.get("/")
    async def gui_root() -> HTMLResponse:
        """Serve the GUI."""
        gui_file = Path(__file__).parent.parent / "gui" / "static" / "index.html"
        if gui_file.exists():
            return HTMLResponse(gui_file.read_text())
        return HTMLResponse("<h1>Guild GUI</h1><p>Static files not found.</p>")

    return app
