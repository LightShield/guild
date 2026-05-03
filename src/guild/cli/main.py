"""Guild CLI — the primary interface."""

from __future__ import annotations

import asyncio
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


def _find_guild_dir() -> Path | None:
    from guild.core.config import find_guild_dir
    return find_guild_dir()


def _require_guild() -> Path:
    gd = _find_guild_dir()
    if not gd or not gd.is_dir():
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
    for sub in ("blocks", "learnings", "artifacts"):
        (guild_dir / sub).mkdir()

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

    async def _init_db():
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        await s.log_audit("project_init", details=str(path.resolve()))
        await s.close()

    asyncio.run(_init_db())
    console.print(f"[green]✓ Guild project initialized at {guild_dir}[/green]")


# --- guild status ---

@app.command()
def status():
    """Show current Guild project status."""
    guild_dir = _require_guild()

    async def _status():
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        tasks = await s.list_tasks()
        agents = await s.list_agents()
        learnings = await s.list_learnings()
        await s.close()
        return tasks, agents, learnings

    tasks, agents, learnings = asyncio.run(_status())

    console.print(f"\n[bold]Guild Project[/bold]: {guild_dir.parent.resolve()}\n")

    if tasks:
        t = Table(title="Tasks")
        t.add_column("ID", style="dim", max_width=8)
        t.add_column("Description")
        t.add_column("Status")
        t.add_column("Agent")
        for row in tasks:
            style = {"done": "green", "failed": "red", "in_progress": "yellow"}.get(row["status"], "")
            t.add_row(row["task_id"][:8], row["description"][:60], f"[{style}]{row['status']}[/]", row["assigned_agent"] or "-")
        console.print(t)
    else:
        console.print("[dim]No tasks yet.[/dim]")

    if agents:
        t = Table(title="Agents")
        t.add_column("ID", style="dim", max_width=8)
        t.add_column("Block")
        t.add_column("Status")
        t.add_column("Tokens")
        for row in agents:
            t.add_row(row["agent_id"][:8], row["block_name"], row["status"], f"{row['token_input']}/{row['token_output']}")
        console.print(t)

    if learnings:
        console.print(f"\n[dim]{len(learnings)} learnings in knowledge base[/dim]")


# --- guild task ---

@app.command()
def task(
    description: str = typer.Argument(..., help="Task description"),
    team: str = typer.Option(None, "--team", "-t", help="Team to use (e.g. dev-loop)"),
    permission: str = typer.Option(None, "--permission", "-p", help="Permission tier override"),
    learn: bool = typer.Option(True, help="Extract learnings after task completes"),
):
    """Create a task and run it with the Guild Master or a team."""
    guild_dir = _require_guild()

    async def _run():
        from guild.blocks.registry import BlockRegistry
        from guild.core.config import load_config
        from guild.core.learning import extract_learnings
        from guild.core.models import PermissionTier
        from guild.core.permissions import PermissionChecker
        from guild.core.storage import Storage
        from guild.core.team_runner import TeamRunner
        from guild.providers.ollama import create_provider

        config = load_config(guild_dir)
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        task_id = uuid.uuid4().hex[:12]
        await storage.create_task(task_id, description)
        console.print(f"[blue]Task:[/blue] {task_id[:8]} — {description}")

        provider = create_provider(config.provider)
        if not await provider.health_check():
            console.print(f"[red]Cannot reach {config.provider.name} at {config.provider.base_url}[/red]")
            console.print("Make sure Ollama is running: [bold]ollama serve[/bold]")
            await storage.update_task(task_id, status="failed", result="Provider unreachable")
            await storage.close()
            raise typer.Exit(1)

        perm_tier = PermissionTier(permission) if permission else config.default_permission

        # Load block registry
        registry = BlockRegistry()
        registry.load_from_dir(guild_dir / "blocks")

        result = ""
        tokens = {"input": 0, "output": 0}

        try:
            if team:
                # Team mode
                team_def = registry.get_team(team)
                if not team_def:
                    console.print(f"[red]Team '{team}' not found. Available: {list(registry.teams.keys())}[/red]")
                    raise typer.Exit(1)

                errors = registry.validate_team(team_def)
                if errors:
                    for e in errors:
                        console.print(f"[red]  {e}[/red]")
                    raise typer.Exit(1)

                console.print(f"[blue]Team:[/blue] {team} ({team_def.description})")
                console.print(f"[blue]Blocks:[/blue] {', '.join(team_def.blocks.keys())}")
                console.print(f"[blue]Permission:[/blue] {perm_tier.value}\n")

                runner = TeamRunner(
                    team=team_def, registry=registry, provider=provider,
                    storage=storage, working_dir=str(guild_dir.parent),
                    permission_tier=perm_tier,
                )
                await storage.update_task(task_id, status="in_progress")
                result = await runner.run(description)
                tokens = runner.total_tokens
            else:
                # Solo mode — Guild Master
                from guild.core.agent import AgentLoop

                agent_id = uuid.uuid4().hex[:12]
                block = config.entry_agent
                block.permission = perm_tier

                checker = PermissionChecker(
                    perm_tier,
                    allowed_paths=[str(guild_dir.parent)],
                )
                agent = AgentLoop(
                    agent_id=agent_id, block=block, provider=provider,
                    storage=storage, working_dir=str(guild_dir.parent),
                    permission_checker=checker,
                )
                await agent.initialize()
                await storage.update_task(task_id, status="in_progress", assigned_agent=agent_id)

                console.print(f"[blue]Agent:[/blue] {agent_id[:8]} ({block.name})")
                console.print(f"[blue]Model:[/blue] {config.provider.model}")
                console.print(f"[blue]Permission:[/blue] {perm_tier.value}\n")

                result = await agent.run(description)
                tokens = {"input": agent.total_input_tokens, "output": agent.total_output_tokens}

            await storage.update_task(task_id, status="done", result=result[:1000])
            console.print(f"\n[green]✓ Task complete[/green]")
            console.print(result)

            # Learning extraction
            if learn:
                console.print("\n[dim]Extracting learnings...[/dim]")
                try:
                    new_learnings = await extract_learnings(task_id, storage, provider)
                    if new_learnings:
                        console.print(f"[dim]Extracted {len(new_learnings)} learnings[/dim]")
                except Exception as e:
                    console.print(f"[dim]Learning extraction failed: {e}[/dim]")

        except KeyboardInterrupt:
            await storage.update_task(task_id, status="failed", result="Interrupted")
            console.print("\n[yellow]Interrupted.[/yellow]")
        except typer.Exit:
            raise
        except Exception as e:
            await storage.update_task(task_id, status="failed", result=str(e)[:500])
            console.print(f"\n[red]Failed: {e}[/red]")
        finally:
            console.print(f"\n[dim]Tokens: {tokens['input']} in / {tokens['output']} out[/dim]")
            await storage.close()

    asyncio.run(_run())


# --- guild chat ---

@app.command()
def chat(
    permission: str = typer.Option("ask", "--permission", "-p", help="Permission tier"),
):
    """Interactive chat with the Guild Master."""
    guild_dir = _require_guild()

    async def _chat():
        from guild.core.agent import AgentLoop
        from guild.core.config import load_config
        from guild.core.models import PermissionTier
        from guild.core.permissions import PermissionChecker
        from guild.core.storage import Storage
        from guild.providers.ollama import create_provider

        config = load_config(guild_dir)
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        provider = create_provider(config.provider)
        if not await provider.health_check():
            console.print(f"[red]Cannot reach Ollama at {config.provider.base_url}[/red]")
            await storage.close()
            raise typer.Exit(1)

        perm_tier = PermissionTier(permission)
        agent_id = uuid.uuid4().hex[:12]
        block = config.entry_agent
        checker = PermissionChecker(perm_tier, allowed_paths=[str(guild_dir.parent)])

        agent = AgentLoop(
            agent_id=agent_id, block=block, provider=provider,
            storage=storage, working_dir=str(guild_dir.parent),
            permission_checker=checker,
        )
        await agent.initialize()

        console.print(f"[bold]Guild Chat[/bold] — talking to {block.name}")
        console.print(f"Model: {config.provider.model} | Permission: {perm_tier.value}")
        console.print("[dim]Type 'exit' or Ctrl+C to quit[/dim]\n")

        try:
            while True:
                try:
                    user_input = console.input("[bold green]you>[/bold green] ")
                except EOFError:
                    break
                if user_input.strip().lower() in ("exit", "quit", "/exit", "/quit"):
                    break
                if not user_input.strip():
                    continue

                result = await agent.run(user_input)
                console.print(f"\n[bold blue]guild-master>[/bold blue] {result}\n")
        except KeyboardInterrupt:
            pass

        console.print(f"\n[dim]Session tokens: {agent.total_input_tokens} in / {agent.total_output_tokens} out[/dim]")
        await storage.close()

    asyncio.run(_chat())


# --- guild models ---

@app.command()
def models():
    """List available Ollama models."""
    async def _list():
        from guild.core.config import load_config
        from guild.providers.ollama import create_provider

        guild_dir = _find_guild_dir()
        config = load_config(guild_dir)
        provider = create_provider(config.provider)

        if not await provider.health_check():
            console.print(f"[red]Cannot reach Ollama at {config.provider.base_url}[/red]")
            raise typer.Exit(1)

        model_list = await provider.list_models()
        if model_list:
            t = Table(title="Available Models")
            t.add_column("Model")
            for m in model_list:
                t.add_row(m)
            console.print(t)
        else:
            console.print("[dim]No models found. Run: ollama pull llama3.2[/dim]")

    asyncio.run(_list())


# --- guild blocks ---

@app.command()
def blocks(
    name: str = typer.Argument(None, help="Block name to show details"),
):
    """List available blocks, or show details of a specific block."""
    from guild.blocks.registry import BlockRegistry

    guild_dir = _find_guild_dir()
    registry = BlockRegistry()
    if guild_dir:
        registry.load_from_dir(guild_dir / "blocks")

    if name:
        block = registry.get_block(name)
        if not block:
            console.print(f"[red]Block '{name}' not found[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]{block.name}[/bold] ({block.role})")
        console.print(f"Prompt: {block.system_prompt[:200]}...")
        console.print(f"Tools: {', '.join(block.tools)}")
        console.print(f"Permission: {block.permission.value}")
        if block.inputs:
            console.print(f"Inputs: {', '.join(f'{p.name}:{p.type_tag}' for p in block.inputs)}")
        if block.outputs:
            console.print(f"Outputs: {', '.join(f'{p.name}:{p.type_tag}' for p in block.outputs)}")
    else:
        t = Table(title="Available Blocks")
        t.add_column("Name")
        t.add_column("Role")
        t.add_column("Tools")
        t.add_column("Inputs")
        t.add_column("Outputs")
        for b in sorted(registry.blocks.values(), key=lambda x: x.name):
            t.add_row(
                b.name, b.role,
                ", ".join(b.tools[:3]) + ("..." if len(b.tools) > 3 else ""),
                ", ".join(f"{p.name}:{p.type_tag}" for p in b.inputs),
                ", ".join(f"{p.name}:{p.type_tag}" for p in b.outputs),
            )
        console.print(t)


# --- guild teams ---

@app.command()
def teams(
    name: str = typer.Argument(None, help="Team name to show details"),
):
    """List available teams, or show details of a specific team."""
    from guild.blocks.registry import BlockRegistry

    guild_dir = _find_guild_dir()
    registry = BlockRegistry()
    if guild_dir:
        registry.load_from_dir(guild_dir / "blocks")

    if name:
        team = registry.get_team(name)
        if not team:
            console.print(f"[red]Team '{name}' not found[/red]")
            raise typer.Exit(1)
        console.print(f"\n[bold]{team.name}[/bold]")
        console.print(f"Description: {team.description}")
        console.print(f"Entry block: {team.entry_block}")
        console.print(f"Blocks: {', '.join(f'{k}({v})' for k, v in team.blocks.items())}")
        if team.connections:
            console.print("Connections:")
            for c in team.connections:
                console.print(f"  {c.source_block}.{c.source_port} → {c.target_block}.{c.target_port}")
        if team.loops:
            console.print("Loops:")
            for l in team.loops:
                console.print(f"  {l.generator_block} ↔ {l.evaluator_block} (max {l.max_iterations} iterations)")

        errors = registry.validate_team(team)
        if errors:
            console.print("\n[red]Validation errors:[/red]")
            for e in errors:
                console.print(f"  [red]{e}[/red]")
        else:
            console.print("\n[green]✓ Valid[/green]")
    else:
        t = Table(title="Available Teams")
        t.add_column("Name")
        t.add_column("Description")
        t.add_column("Blocks")
        t.add_column("Loops")
        for team in sorted(registry.teams.values(), key=lambda x: x.name):
            t.add_row(
                team.name, team.description,
                ", ".join(team.blocks.keys()),
                str(len(team.loops)),
            )
        console.print(t)


# --- guild learnings ---

@app.command()
def learnings():
    """Show extracted learnings from past tasks."""
    guild_dir = _require_guild()

    async def _list():
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        items = await s.list_learnings()
        await s.close()
        return items

    items = asyncio.run(_list())
    if not items:
        console.print("[dim]No learnings yet. Complete a task to extract learnings.[/dim]")
        return

    t = Table(title="Learnings")
    t.add_column("Category")
    t.add_column("Content")
    t.add_column("Confidence")
    t.add_column("Source Task", style="dim", max_width=8)
    for l in items:
        conf = f"{l['confidence']:.0%}"
        t.add_row(l["category"], l["content"][:80], conf, (l.get("source_task_id") or "")[:8])
    console.print(t)


if __name__ == "__main__":
    app()
