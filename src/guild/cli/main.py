"""Guild CLI — the primary interface.

All features are accessible via CLI commands. The GUI is a wrapper on top of this.
"""

from __future__ import annotations

__all__ = ["app"]

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

# Global RPG mode flag
_rpg_mode = False


def _out(text: str) -> None:
    """Print text, applying RPG translation if enabled."""
    if _rpg_mode:
        from guild.core.rpg import rpg_translate
        text = rpg_translate(text)
    console.print(text)


def _find_guild_dir() -> Path | None:
    """Find the .guild directory."""
    from guild.core.config import find_guild_dir
    return find_guild_dir()


def _require_guild() -> Path:
    """Get guild dir or exit with error."""
    gd = _find_guild_dir()
    if not gd or not gd.is_dir():
        console.print("[red]Not a Guild project. Run 'guild init' first.[/red]")
        raise typer.Exit(1)
    return gd


def _rpg_callback(value: bool) -> None:
    """Callback for --rpg flag."""
    global _rpg_mode
    _rpg_mode = value


@app.callback()
def main_callback(
    rpg: bool = typer.Option(False, "--rpg", help="Enable RPG fun mode", callback=_rpg_callback, is_eager=True),
    version: bool = typer.Option(False, "--version", "-V", help="Show version", is_eager=True),
) -> None:
    """Guild — locally-focused agent harness for LLM-powered teams."""
    if version:
        from guild import __version__
        console.print(f"Guild v{__version__}")
        raise typer.Exit(0)


# --- guild init ---

@app.command()
def init(path: Path = typer.Argument(Path("."), help="Directory to initialize")) -> None:
    """Initialize a new Guild project."""
    guild_dir = path / GUILD_DIR
    if guild_dir.exists():
        _out(f"[yellow]Guild project already exists at {guild_dir}[/yellow]")
        raise typer.Exit(0)

    guild_dir.mkdir(parents=True)
    for sub in ("blocks", "learnings", "artifacts", "templates"):
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
max_concurrent_tool_calls = 4
"""
    (guild_dir / CONFIG_NAME).write_text(config_content)

    async def _init_db() -> None:
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        await s.log_audit("project_init", details=str(path.resolve()))
        await s.close()

    asyncio.run(_init_db())
    _out(f"[green]✓ Guild project initialized at {guild_dir}[/green]")


# --- guild status ---

@app.command()
def status() -> None:
    """Show current Guild project status."""
    guild_dir = _require_guild()

    async def _status() -> tuple:
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        tasks = await s.list_tasks()
        agents = await s.list_agents()
        learnings = await s.list_learnings()
        await s.close()
        return tasks, agents, learnings

    tasks, agents, learnings = asyncio.run(_status())

    _out(f"\n[bold]Guild Project[/bold]: {guild_dir.parent.resolve()}\n")

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
        _out("[dim]No tasks yet.[/dim]")

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
        _out(f"\n[dim]{len(learnings)} learnings in knowledge base[/dim]")


# --- guild task ---

@app.command()
def task(
    description: str = typer.Argument(..., help="Task description"),
    team: str = typer.Option(None, "--team", "-t", help="Team to use"),
    permission: str = typer.Option(None, "--permission", "-p", help="Permission tier"),
    learn: bool = typer.Option(True, help="Extract learnings after task"),
    timeout: int = typer.Option(0, "--timeout", help="Timeout in seconds (0=none)"),
    template: str = typer.Option(None, "--template", help="Use a workflow template"),
) -> None:
    """Create a task and run it with the Guild Master or a team."""
    guild_dir = _require_guild()

    async def _run() -> None:
        from guild.blocks.registry import BlockRegistry
        from guild.core.agent import AgentLoop
        from guild.core.artifacts import ArtifactManager
        from guild.core.config import load_config
        from guild.core.learning import extract_learnings
        from guild.core.models import PermissionTier
        from guild.core.offline import OfflineManager
        from guild.core.permissions import PermissionChecker
        from guild.core.ratelimit import RateLimiter, ToolQueue
        from guild.core.storage import Storage
        from guild.core.team_runner import TeamRunner
        from guild.core.templates import TemplateManager
        from guild.providers.ollama import create_provider
        from guild.providers.router import ModelRouter

        config = load_config(guild_dir)
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        # Resolve template if specified
        actual_description = description
        actual_team = team
        if template:
            tmgr = TemplateManager(guild_dir / "templates")
            tmpl = tmgr.get(template)
            if not tmpl:
                _out(f"[red]Template '{template}' not found.[/red]")
                await storage.close()
                raise typer.Exit(1)
            # Use description as the value for all template parameters
            params = {p: description for p in tmpl.parameters} if description else {}
            actual_description = tmpl.render(**params)
            actual_team = actual_team or tmpl.team
            _out(f"[blue]Template:[/blue] {tmpl.name}")

        task_id = uuid.uuid4().hex[:12]
        await storage.create_task(task_id, actual_description)
        _out(f"[blue]Task:[/blue] {task_id[:8]} — {actual_description}")

        # Create provider with offline check
        provider = create_provider(config.provider)
        offline_mgr = OfflineManager(provider)
        if not await offline_mgr.check_connectivity():
            _out(f"[red]Cannot reach {config.provider.name} at {config.provider.base_url}[/red]")
            _out("Make sure Ollama is running:")
            _out("  1. Install: [bold]curl -fsSL https://ollama.ai/install.sh | sh[/bold]")
            _out("  2. Start:   [bold]ollama serve[/bold]")
            _out(f"  3. Pull:    [bold]ollama pull {config.provider.model}[/bold]")
            await storage.update_task(task_id, status="failed", result="Provider unreachable")
            await storage.close()
            raise typer.Exit(1)

        perm_tier = PermissionTier(permission) if permission else config.default_permission
        registry = BlockRegistry()
        registry.load_from_dir(guild_dir / "blocks")
        artifacts = ArtifactManager(guild_dir / "artifacts", storage)
        rate_limiter = RateLimiter(max_calls=30, window_seconds=60.0)
        tool_queue = ToolQueue(max_concurrent=config.max_concurrent_tool_calls)

        result = ""
        tokens = {"input": 0, "output": 0}

        try:
            if actual_team:
                team_def = registry.get_team(actual_team)
                if not team_def:
                    _out(f"[red]Team '{actual_team}' not found. Available: {list(registry.teams.keys())}[/red]")
                    raise typer.Exit(1)
                errors = registry.validate_team(team_def)
                if errors:
                    for e in errors:
                        _out(f"[red]  {e}[/red]")
                    raise typer.Exit(1)

                _out(f"[blue]Team:[/blue] {actual_team} ({team_def.description})")
                _out(f"[blue]Permission:[/blue] {perm_tier.value}\n")

                runner = TeamRunner(
                    team=team_def, registry=registry, provider=provider,
                    storage=storage, working_dir=str(guild_dir.parent),
                    permission_tier=perm_tier,
                )
                await storage.update_task(task_id, status="in_progress")
                result = await runner.run(actual_description)
                tokens = runner.total_tokens
            else:
                agent_id = uuid.uuid4().hex[:12]
                block = config.entry_agent
                block.permission = perm_tier
                checker = PermissionChecker(perm_tier, allowed_paths=[str(guild_dir.parent)])
                agent = AgentLoop(
                    agent_id=agent_id, block=block, provider=provider,
                    storage=storage, working_dir=str(guild_dir.parent),
                    permission_checker=checker, timeout_seconds=timeout or None,
                    rate_limiter=rate_limiter, tool_queue=tool_queue,
                    context_window=config.provider.max_tokens,
                )
                await agent.initialize()
                await storage.update_task(task_id, status="in_progress", assigned_agent=agent_id)
                _out(f"[blue]Agent:[/blue] {agent_id[:8]} ({block.name})")
                _out(f"[blue]Model:[/blue] {config.provider.model}")
                _out(f"[blue]Permission:[/blue] {perm_tier.value}\n")
                result = await agent.run(actual_description)
                tokens = {"input": agent.total_input_tokens, "output": agent.total_output_tokens}

            await storage.update_task(task_id, status="done", result=result[:1000])
            artifacts.save(task_id, "result.txt", result)
            _out(f"\n[green]✓ Task complete[/green]")
            _out(result)

            if learn:
                _out("\n[dim]Extracting learnings...[/dim]")
                try:
                    new_learnings = await extract_learnings(task_id, storage, provider)
                    if new_learnings:
                        _out(f"[dim]Extracted {len(new_learnings)} learnings[/dim]")
                except Exception as e:
                    _out(f"[dim]Learning extraction failed: {e}[/dim]")

        except KeyboardInterrupt:
            await storage.update_task(task_id, status="failed", result="Interrupted")
            _out("\n[yellow]Interrupted.[/yellow]")
        except typer.Exit:
            raise
        except Exception as e:
            await storage.update_task(task_id, status="failed", result=str(e)[:500])
            _out(f"\n[red]Failed: {e}[/red]")
        finally:
            _out(f"\n[dim]Tokens: {tokens['input']} in / {tokens['output']} out[/dim]")
            await storage.close()

    asyncio.run(_run())


# --- guild chat ---

@app.command()
def chat(
    permission: str = typer.Option("ask", "--permission", "-p", help="Permission tier"),
) -> None:
    """Interactive chat with the Guild Master."""
    guild_dir = _require_guild()

    async def _chat() -> None:
        from guild.core.agent import AgentLoop
        from guild.core.config import load_config
        from guild.core.models import PermissionTier
        from guild.core.offline import OfflineManager
        from guild.core.permissions import PermissionChecker
        from guild.core.ratelimit import RateLimiter
        from guild.core.storage import Storage
        from guild.providers.ollama import create_provider

        config = load_config(guild_dir)
        storage = Storage(guild_dir / DB_NAME)
        await storage.connect()

        provider = create_provider(config.provider)
        offline_mgr = OfflineManager(provider)
        if not await offline_mgr.check_connectivity():
            _out(f"[red]Cannot reach Ollama at {config.provider.base_url}[/red]")
            await storage.close()
            raise typer.Exit(1)

        perm_tier = PermissionTier(permission)
        agent_id = uuid.uuid4().hex[:12]
        block = config.entry_agent
        checker = PermissionChecker(perm_tier, allowed_paths=[str(guild_dir.parent)])
        rate_limiter = RateLimiter(max_calls=30, window_seconds=60.0)

        agent = AgentLoop(
            agent_id=agent_id, block=block, provider=provider,
            storage=storage, working_dir=str(guild_dir.parent),
            permission_checker=checker, rate_limiter=rate_limiter,
            context_window=config.provider.max_tokens,
        )
        await agent.initialize()

        _out(f"[bold]Guild Chat[/bold] — talking to {block.name}")
        _out(f"Model: {config.provider.model} | Permission: {perm_tier.value}")
        _out("[dim]Type 'exit' or Ctrl+C to quit[/dim]\n")

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
                _out(f"\n[bold blue]guild-master>[/bold blue] {result}\n")
        except KeyboardInterrupt:
            pass

        _out(f"\n[dim]Session tokens: {agent.total_input_tokens} in / {agent.total_output_tokens} out[/dim]")
        await storage.close()

    asyncio.run(_chat())


# --- guild models ---

@app.command()
def models() -> None:
    """List available Ollama models."""
    async def _list() -> None:
        from guild.core.config import load_config
        from guild.core.offline import OfflineManager
        from guild.providers.ollama import create_provider

        guild_dir = _find_guild_dir()
        config = load_config(guild_dir)
        provider = create_provider(config.provider)
        offline_mgr = OfflineManager(provider)

        if not await offline_mgr.check_connectivity():
            _out(f"[red]Cannot reach Ollama at {config.provider.base_url}[/red]")
            raise typer.Exit(1)

        model_list = await offline_mgr.list_local_models()
        if model_list:
            t = Table(title="Available Models")
            t.add_column("Model")
            for m in model_list:
                t.add_row(m)
            console.print(t)
        else:
            _out("[dim]No models found. Run: ollama pull llama3.2[/dim]")

    asyncio.run(_list())


# --- guild blocks ---

@app.command()
def blocks(name: str = typer.Argument(None, help="Block name to show details")) -> None:
    """List available blocks, or show details of a specific block."""
    from guild.blocks.registry import BlockRegistry

    guild_dir = _find_guild_dir()
    registry = BlockRegistry()
    if guild_dir:
        registry.load_from_dir(guild_dir / "blocks")

    if name:
        block = registry.get_block(name)
        if not block:
            _out(f"[red]Block '{name}' not found[/red]")
            raise typer.Exit(1)
        _out(f"\n[bold]{block.name}[/bold] ({block.role})")
        _out(f"Prompt: {block.system_prompt[:200]}...")
        _out(f"Tools: {', '.join(block.tools)}")
        _out(f"Permission: {block.permission.value}")
        if block.inputs:
            _out(f"Inputs: {', '.join(f'{p.name}:{p.type_tag}' for p in block.inputs)}")
        if block.outputs:
            _out(f"Outputs: {', '.join(f'{p.name}:{p.type_tag}' for p in block.outputs)}")
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
def teams(name: str = typer.Argument(None, help="Team name to show details")) -> None:
    """List available teams, or show details of a specific team."""
    from guild.blocks.registry import BlockRegistry

    guild_dir = _find_guild_dir()
    registry = BlockRegistry()
    if guild_dir:
        registry.load_from_dir(guild_dir / "blocks")

    if name:
        t = registry.get_team(name)
        if not t:
            _out(f"[red]Team '{name}' not found[/red]")
            raise typer.Exit(1)
        _out(f"\n[bold]{t.name}[/bold]")
        _out(f"Description: {t.description}")
        _out(f"Entry block: {t.entry_block}")
        _out(f"Blocks: {', '.join(f'{k}({v})' for k, v in t.blocks.items())}")
        if t.connections:
            _out("Connections:")
            for c in t.connections:
                _out(f"  {c.source_block}.{c.source_port} → {c.target_block}.{c.target_port}")
        if t.loops:
            _out("Loops:")
            for l in t.loops:
                _out(f"  {l.generator_block} ↔ {l.evaluator_block} (max {l.max_iterations} iterations)")
        errors = registry.validate_team(t)
        _out(f"\n[green]✓ Valid[/green]" if not errors else "")
        for e in errors:
            _out(f"  [red]{e}[/red]")
    else:
        tbl = Table(title="Available Teams")
        tbl.add_column("Name")
        tbl.add_column("Description")
        tbl.add_column("Blocks")
        tbl.add_column("Loops")
        for t in sorted(registry.teams.values(), key=lambda x: x.name):
            tbl.add_row(t.name, t.description, ", ".join(t.blocks.keys()), str(len(t.loops)))
        console.print(tbl)


# --- guild learnings ---

@app.command()
def learnings() -> None:
    """Show extracted learnings from past tasks."""
    guild_dir = _require_guild()

    async def _list() -> list[dict]:
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        items = await s.list_learnings()
        await s.close()
        return items

    items = asyncio.run(_list())
    if not items:
        _out("[dim]No learnings yet. Complete a task to extract learnings.[/dim]")
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


# --- guild audit ---

@app.command()
def audit(limit: int = typer.Option(50, "--limit", "-n", help="Max entries")) -> None:
    """Show audit log of agent actions and permission decisions."""
    guild_dir = _require_guild()

    async def _list() -> list[dict]:
        from guild.core.storage import Storage
        s = Storage(guild_dir / DB_NAME)
        await s.connect()
        items = await s.list_audit(limit=limit)
        await s.close()
        return items

    items = asyncio.run(_list())
    if not items:
        _out("[dim]No audit entries yet.[/dim]")
        return

    t = Table(title="Audit Log")
    t.add_column("Timestamp", style="dim", max_width=19)
    t.add_column("Agent", max_width=12)
    t.add_column("Action")
    t.add_column("Details", max_width=60)
    for row in items:
        t.add_row(
            (row.get("timestamp") or "")[:19], row.get("agent_id") or "-",
            row["action"], (row.get("details") or "")[:60],
        )
    console.print(t)


# --- guild config ---

@app.command()
def config(
    set_value: str = typer.Option(None, "--set", help="Set a config value: section.key=value"),
) -> None:
    """Show or modify project configuration."""
    guild_dir = _require_guild()
    config_path = guild_dir / CONFIG_NAME

    if set_value:
        if "=" not in set_value:
            _out("[red]Format: --set section.key=value[/red]")
            raise typer.Exit(1)
        path_part, value = set_value.split("=", 1)
        parts = path_part.split(".")
        if len(parts) != 2:
            _out("[red]Format: --set section.key=value[/red]")
            raise typer.Exit(1)
        section, key = parts

        import tomllib
        raw = {}
        if config_path.exists():
            with open(config_path, "rb") as f:
                raw = tomllib.load(f)
        if section not in raw:
            raw[section] = {}
        try:
            parsed: int | float | bool | str = int(value)
        except ValueError:
            try:
                parsed = float(value)
            except ValueError:
                parsed = value.lower() == "true" if value.lower() in ("true", "false") else value
        raw[section][key] = parsed

        lines = []
        for sec, vals in raw.items():
            lines.append(f"[{sec}]")
            for k, v in vals.items():
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                elif isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")
        config_path.write_text("\n".join(lines))
        _out(f"[green]✓ Set {section}.{key} = {parsed}[/green]")
    else:
        if config_path.exists():
            console.print(config_path.read_text())
        else:
            _out("[dim]No config file found.[/dim]")


# --- guild templates ---

@app.command()
def templates(
    name: str = typer.Argument(None, help="Template name to show details"),
) -> None:
    """List or show workflow templates."""
    guild_dir = _require_guild()
    from guild.core.templates import TemplateManager

    mgr = TemplateManager(guild_dir / "templates")
    items = mgr.list()

    if name:
        tmpl = mgr.get(name)
        if not tmpl:
            _out(f"[red]Template '{name}' not found[/red]")
            raise typer.Exit(1)
        _out(f"\n[bold]{tmpl.name}[/bold]")
        _out(f"Description: {tmpl.description}")
        _out(f"Team: {tmpl.team or 'none'}")
        _out(f"Task template: {tmpl.task_template}")
        _out(f"Parameters: {', '.join(tmpl.parameters) or 'none'}")
    else:
        if not items:
            _out("[dim]No templates yet. Create .guild/templates/*.toml files.[/dim]")
            return
        t = Table(title="Workflow Templates")
        t.add_column("Name")
        t.add_column("Description")
        t.add_column("Team")
        t.add_column("Parameters")
        for tmpl in items:
            t.add_row(tmpl.name, tmpl.description, tmpl.team or "-", ", ".join(tmpl.parameters) or "-")
        console.print(t)


# --- guild artifacts ---

@app.command()
def artifacts(
    task_id: str = typer.Argument(None, help="Task ID to list artifacts for"),
) -> None:
    """List artifacts produced by tasks."""
    guild_dir = _require_guild()
    from guild.core.artifacts import ArtifactManager
    from guild.core.storage import Storage

    mgr = ArtifactManager(guild_dir / "artifacts", Storage(guild_dir / DB_NAME))

    if task_id:
        files = mgr.list_for_task(task_id)
        if not files:
            _out(f"[dim]No artifacts for task {task_id[:8]}[/dim]")
            return
        for f in files:
            _out(f"  {f.name} ({f.stat().st_size} bytes)")
    else:
        artifacts_dir = guild_dir / "artifacts"
        if not artifacts_dir.is_dir():
            _out("[dim]No artifacts yet.[/dim]")
            return
        task_dirs = sorted(d for d in artifacts_dir.iterdir() if d.is_dir())
        if not task_dirs:
            _out("[dim]No artifacts yet.[/dim]")
            return
        t = Table(title="Artifacts")
        t.add_column("Task", style="dim", max_width=12)
        t.add_column("Files")
        for td in task_dirs:
            files = list(td.iterdir())
            t.add_row(td.name[:12], ", ".join(f.name for f in files))
        console.print(t)


# --- guild serve ---

@app.command()
def serve(
    port: int = typer.Option(8585, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
) -> None:
    """Start the Guild web GUI and API server."""
    _require_guild()
    import uvicorn
    from guild.api.server import create_app

    _out(f"[bold]Guild GUI[/bold] starting at http://{host}:{port}")
    _out("[dim]Press Ctrl+C to stop[/dim]")
    web_app = create_app()
    uvicorn.run(web_app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()
