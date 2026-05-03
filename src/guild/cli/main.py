"""Guild CLI — the primary interface."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="guild", help="Guild — locally-focused agent harness for LLM-powered teams.")
console = Console()

GUILD_DIR = ".guild"
DB_NAME = "guild.db"
CONFIG_NAME = "config.toml"


def get_guild_dir() -> Path:
    """Find the .guild directory in current or parent directories."""
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        gd = p / GUILD_DIR
        if gd.is_dir():
            return gd
    return cwd / GUILD_DIR


def require_guild() -> Path:
    """Get guild dir or exit with error."""
    gd = get_guild_dir()
    if not gd.is_dir():
        console.print("[red]Not a Guild project. Run 'guild init' first.[/red]")
        raise typer.Exit(1)
    return gd


# --- guild init ---

@app.command()
def init(path: Path = typer.Argument(Path("."), help="Directory to initialize")):
    """Initialize a new Guild project."""
    guild_dir = path / GUILD_DIR
    if guild_dir.exists():
        console.print(f"[yellow]Guild project already exists at {guild_dir}[/yellow]")
        raise typer.Exit(0)

    guild_dir.mkdir(parents=True)
    (guild_dir / "blocks").mkdir()
    (guild_dir / "learnings").mkdir()
    (guild_dir / "artifacts").mkdir()

    # Create default config
    config_content = """\
[provider]
name = "ollama"
base_url = "http://localhost:11434"
model = "llama3.2"
temperature = 0.7
max_tokens = 4096

[guild]
default_permission = "ask"
max_concurrent_agents = 1
"""
    (guild_dir / CONFIG_NAME).write_text(config_content)

    # Create empty DB by connecting and running schema
    async def _init_db():
        from guild.core.storage import Storage
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()
        await storage.log_audit("project_init", details=str(path.resolve()))
        await storage.close()

    asyncio.run(_init_db())

    console.print(f"[green]✓ Guild project initialized at {guild_dir}[/green]")
    console.print(f"  Database: {guild_dir / DB_NAME}")
    console.print(f"  Config:   {guild_dir / CONFIG_NAME}")


# --- guild status ---

@app.command()
def status():
    """Show current Guild project status."""
    guild_dir = require_guild()

    async def _status():
        from guild.core.storage import Storage
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        tasks = await storage.list_tasks()
        agents = await storage.list_agents()
        await storage.close()
        return tasks, agents

    tasks, agents = asyncio.run(_status())

    console.print(f"\n[bold]Guild Project[/bold]: {guild_dir.parent.resolve()}")
    console.print(f"Database: {guild_dir / DB_NAME}\n")

    # Tasks table
    if tasks:
        table = Table(title="Tasks")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Description")
        table.add_column("Status")
        table.add_column("Agent")
        for t in tasks:
            status_style = {"done": "green", "failed": "red", "in_progress": "yellow"}.get(t["status"], "")
            table.add_row(t["task_id"][:8], t["description"][:60], f"[{status_style}]{t['status']}[/]", t["assigned_agent"] or "-")
        console.print(table)
    else:
        console.print("[dim]No tasks yet. Run 'guild task \"description\"' to create one.[/dim]")

    # Agents table
    if agents:
        table = Table(title="Agents")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Block")
        table.add_column("Status")
        table.add_column("Tokens (in/out)")
        for a in agents:
            table.add_row(a["agent_id"][:8], a["block_name"], a["status"], f"{a['token_input']}/{a['token_output']}")
        console.print(table)


# --- guild task ---

@app.command()
def task(description: str = typer.Argument(..., help="Task description")):
    """Create a task and run it with the Guild Master agent."""
    guild_dir = require_guild()

    async def _run_task():
        import tomllib

        from guild.core.agent import AgentLoop
        from guild.core.models import GuildConfig
        from guild.core.storage import Storage
        from guild.providers.ollama import create_provider

        # Load config
        config_path = guild_dir / CONFIG_NAME
        if config_path.exists():
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
        else:
            raw = {}

        config = GuildConfig()
        if "provider" in raw:
            for k, v in raw["provider"].items():
                setattr(config.provider, k, v)

        # Init storage
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        # Create task
        task_id = uuid.uuid4().hex[:12]
        await storage.create_task(task_id, description)
        console.print(f"[blue]Task created:[/blue] {task_id[:8]} — {description}")

        # Check provider health
        provider = create_provider(config.provider)
        healthy = await provider.health_check()
        if not healthy:
            console.print(f"[red]Cannot reach {config.provider.name} at {config.provider.base_url}[/red]")
            console.print("Make sure Ollama is running: [bold]ollama serve[/bold]")
            await storage.update_task(task_id, status="failed", result="Provider unreachable")
            await storage.close()
            raise typer.Exit(1)

        # Create and run agent
        agent_id = uuid.uuid4().hex[:12]
        block = config.entry_agent
        agent = AgentLoop(
            agent_id=agent_id,
            block=block,
            provider=provider,
            storage=storage,
            working_dir=str(guild_dir.parent),
        )

        await agent.initialize()
        await storage.update_task(task_id, status="in_progress", assigned_agent=agent_id)

        console.print(f"[blue]Agent started:[/blue] {agent_id[:8]} ({block.name})")
        console.print(f"[blue]Model:[/blue] {config.provider.model}")
        console.print()

        try:
            result = await agent.run(description)
            await storage.update_task(task_id, status="done", result=result[:1000])
            console.print(f"\n[green]✓ Task complete[/green]")
            console.print(result)
        except KeyboardInterrupt:
            await storage.update_task(task_id, status="failed", result="Interrupted by user")
            console.print("\n[yellow]Task interrupted.[/yellow]")
        except Exception as e:
            await storage.update_task(task_id, status="failed", result=str(e)[:500])
            console.print(f"\n[red]Task failed: {e}[/red]")
        finally:
            console.print(f"\n[dim]Tokens: {agent.total_input_tokens} in / {agent.total_output_tokens} out[/dim]")
            await storage.close()

    asyncio.run(_run_task())


# --- guild models ---

@app.command()
def models():
    """List available Ollama models."""
    async def _list():
        import tomllib
        from guild.core.models import ProviderConfig
        from guild.providers.ollama import create_provider

        guild_dir = get_guild_dir()
        config_path = guild_dir / CONFIG_NAME
        if config_path.exists():
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
            pc = ProviderConfig(**raw.get("provider", {}))
        else:
            pc = ProviderConfig()

        provider = create_provider(pc)
        if not await provider.health_check():
            console.print(f"[red]Cannot reach Ollama at {pc.base_url}[/red]")
            raise typer.Exit(1)

        model_list = await provider.list_models()
        if model_list:
            table = Table(title="Available Models")
            table.add_column("Model")
            for m in model_list:
                table.add_row(m)
            console.print(table)
        else:
            console.print("[dim]No models found. Run: ollama pull llama3.2[/dim]")

    asyncio.run(_list())


if __name__ == "__main__":
    app()
