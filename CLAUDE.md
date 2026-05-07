# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Guild is a locally-focused agent harness for running an autonomous coding agent against local models (Ollama). Core value: an agent that works while you're away and backs off when you're present ("good neighbor"). Version 0.2.0.

## Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest                                    # all tests (including integration)
pytest -m unit                            # unit tests only (fast, no network)
pytest -m integration                     # integration tests (requires Ollama)
pytest tests/agent/                       # single directory
pytest tests/agent/test_loop.py::TestAgentLoop::test_loop_exits_on_text_only_response

# Linting and formatting
ruff check src/ tests/
ruff check --fix src/ tests/
black src/ tests/

# Requirements traceability
python scripts/req_coverage.py            # RTM report

# Run the CLI
guild --help
guild init                                # initialize .guild/ in current dir
guild task "description"                  # run a task (foreground)
guild task "description" --background     # background daemon
guild chat                                # interactive multi-turn
guild status / guild ps                   # project status / running tasks
guild kill/pause/resume <task_id>         # process lifecycle
guild logs/attach <task_id>               # view or interact with task
guild history / guild usage               # past tasks / token summary
guild learnings / guild decisions         # knowledge base
guild questions / guild answer            # human-in-the-loop queue
guild config / guild audit                # configuration / audit log
guild resource-status                     # scheduling mode and throttle state
```

## Architecture

**Three-layer design:**
- Layer 1 (Harness): process lifecycle, resource management, tools, storage, permissions
- Layer 2 (Agent Behaviors): decision framework, self-review, learning, escalation
- Layer 3 (Orchestration): teams, decomposition, multi-agent coordination

### Domain-Grouped Structure

```
src/guild/
├── agent/          — Core loop, completion, stuck detection, rollback, checkpoint, learning, cost, budget, rate limiting, context management
├── provider/       — LLM abstraction (base, Ollama, CLI tool, escalation chain)
├── storage/        — SQLite persistence (tasks, messages, audit, decisions, learnings, questions, checkpoints, memories)
├── tools/          — Built-in tools (file_read, file_write, shell, search, glob, spawn_agent)
├── permissions/    — 4-tier permission + hardcoded-never layer
├── config/         — ConfigsLoader-based config, profiles, validation
├── daemon/         — Background execution, lifecycle, resource monitor, sleep/wake
├── cli/            — Typer CLI (all commands)
├── orchestration/  — Message bus, agent spawner, team runner, shared context
├── blocks/         — Block definitions, registry, port types, skills
├── git/            — Worktree manager, branch policy
├── knowledge/      — Temporal knowledge, memory index
├── security/       — Sandbox policy (paths, commands, secrets, network)
├── escalation/     — Question queue, notification channels
├── observability/  — Structured tracing, log export, session replay
├── task/           — Task specs, verification, status lifecycle
├── artifacts/      — Artifact versioning, diff, export
├── templates/      — Workflow templates (save, render, import/export)
├── offline/        — Offline-first manager (connectivity, model management)
├── ui/             — RPG mode theming
└── api/            — REST API stub (requires fastapi optional dep)
```

## Code Conventions

- Python 3.11+, all modules have `__all__` exports
- ConfigsLoader for config, dataclasses for internal data
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
- Tests mirror src structure: `tests/agent/`, `tests/provider/`, etc.
- 635 tests total (631 unit + 4 integration)

## Design Principles

1. **Reversibility governs everything** — planning, decisions, permissions calibrated by "how hard to undo?"
2. **Maximize autonomous progress** — user never the bottleneck unless truly irreversible
3. **Adapt to user presence** — attached: interactive. Detached: autonomous. Resource monitor drives this.
4. **Senior engineer mindset** — opinionated, documents rationale, asks only when genuinely stuck
5. **Three separate layers** — harness / behaviors / orchestration evolve independently
6. **Fix, log, and learn** — every mistake feeds the confidence-scored learning loop

## Remote Ollama Setup

Development uses a remote Ollama instance on the LAN:
```bash
./scripts/remote-ollama-setup.sh --client 192.168.0.110
guild config --set provider.base_url=http://192.168.0.110:11434
```
