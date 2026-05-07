# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Guild is a locally-focused agent harness for running an autonomous coding agent against local models (Ollama). Core value: an agent that works while you're away and backs off when you're present ("good neighbor"). Early development — v0.2.0.

## Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest                                    # all tests
pytest -m unit                            # unit tests only (fast, no network)
pytest -m integration                     # integration tests (requires Ollama)
pytest tests/agent/test_loop.py           # single file
pytest tests/agent/test_loop.py::TestAgentLoop::test_loop_exits_on_text_only_response  # single test

# Linting and formatting
ruff check src/ tests/                    # lint
ruff check --fix src/ tests/             # auto-fix
black src/ tests/                         # format

# Type checking
mypy src/

# Requirements traceability
python scripts/req_coverage.py            # show coverage report

# Run the CLI
guild --help
guild init                                # initialize .guild/ in current dir
guild task "description"                  # run a task (foreground)
guild task "description" --background     # run as background daemon
guild chat                                # interactive chat
guild status                              # project status
guild ps                                  # list running background tasks
guild kill <task_id>                      # stop a background task
guild pause/resume <task_id>              # pause/resume a task
guild logs <task_id>                      # stream task output
guild config                              # show config
guild config --set provider.model=x       # modify config
guild audit                               # show audit log

# Remote Ollama (for LAN development)
./scripts/remote-ollama-setup.sh --client <ip>
```

## Architecture

**Single-process async model.** The agent loop is async, tools execute via asyncio, state persists in SQLite (WAL mode).

### Domain-Grouped Structure

```
src/guild/
├── agent/       — Core loop, completion heuristics, stuck detection
├── provider/    — LLM abstraction (base ABC + Ollama implementation)
├── storage/     — SQLite persistence (tasks, messages, audit)
├── tools/       — Built-in tools (file_read, file_write, shell, search, glob)
├── permissions/ — 4-tier permission enforcement
├── config/      — ConfigsLoader-based config (TOML + CLI + env)
├── daemon/      — Background execution, lifecycle, resource monitor, sleep/wake
└── cli/         — Typer CLI (all commands in main.py)
```

### Core Concepts

- **AgentLoop**: while-loop calling model → executing tools → repeating. Integrates 3 anti-looping fixes (enriched results, completion nudge, dedup guard).
- **Permission tiers**: `nothing` → `ask` → `scoped` → `autopilot`
- **DaemonSupervisor**: PID files, signal handlers, supervised execution for background tasks
- **ResourceMonitor**: 3 modes (full/polite/stealth) — throttles when user is active
- **SleepWakeDetector**: time-drift detection, provider recovery on wake
- **Storage**: All state in `.guild/guild.db` (tasks, agents, messages, audit log)

### Data Flow

`CLI command` → `load_config()` → `create_provider()` → `AgentLoop` → tool calls → results stored in SQLite

### Config System

Uses `configsloader` (custom lib at ../configs_loader_python). One flat class with per-field TOML sections:
```python
class GuildConfig(ConfigsLoader):
    model: str = Field(default="gemma4-4b", section="provider", flags=["--model"])
    base_url: str = Field(default="http://localhost:11434", section="provider")
    default_permission: PermissionTier = Field(default=PermissionTier.ASK, section="guild")
```

## Code Conventions

- Python 3.11+, all modules have `__all__` exports
- ConfigsLoader for config (replaces Pydantic), dataclasses for internal data
- All I/O is async (`aiosqlite`, `asyncio.create_subprocess_shell`)
- No `print()` — use `logging` in library code, `rich.console` in CLI
- Line length: 100 (ruff + black)
- Max function length ~50 lines, max 5 params
- Early exit / guard clauses
- Domain-grouped directory structure

## Testing Strategy

Requirements-Based Testing (RBT) with auto-generated RTM:
- Every test tagged with `@pytest.mark.req("REQ-XX.X")`
- `scripts/req_coverage.py` generates the traceability matrix
- Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`
- `pytest-asyncio` with `asyncio_mode = "auto"`
- Integration tests hit real Ollama at configured address
- Tests mirror src structure: `tests/agent/`, `tests/provider/`, etc.

## Remote Ollama Setup

Development uses a remote Ollama instance on the LAN:
```bash
./scripts/remote-ollama-setup.sh --client 192.168.0.110
guild config --set provider.base_url=http://192.168.0.110:11434
```
