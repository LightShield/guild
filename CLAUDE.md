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

# Type checking
mypy src/guild/ --strict                  # must pass with zero errors

# Linting and formatting
ruff check src/ tests/
ruff check --fix src/ tests/
black src/ tests/

# Requirements traceability (scans Python + Playwright E2E tests)
python scripts/req_coverage.py            # RTM report (212/213 requirements)

# Frontend E2E tests (requires npm install in ui/)
cd ui && npm run build && npx playwright test

# Run the CLI
guild --help
guild init                                # initialize .guild/ in current dir
guild task "description"                  # run a task (foreground)
guild task "description" --background     # background daemon
guild chat                                # interactive multi-turn
guild status / guild ps                   # project status / running tasks
guild kill/pause/resume <task_id>         # process lifecycle
guild attach <task_id>                    # interactive attach via control socket
guild logs <task_id>                      # view task messages
guild history / guild usage               # past tasks / token summary
guild learnings / guild decisions         # knowledge base
guild questions / guild answer            # human-in-the-loop queue
guild config / guild audit                # configuration / audit log
guild resource-status                     # scheduling mode and throttle state
guild serve                               # start REST API + GUI
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
├── config/         — ConfigsLoader-based config, constants, profiles, validation
├── daemon/         — Background execution, lifecycle, resource monitor, sleep/wake, control socket, platform adapter
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
└── api/            — REST API + A2A gateway (requires fastapi optional dep)
```

### Key Infrastructure

- **`config/constants.py`** — Single source of truth for all operational constants (timeouts, thresholds, filenames)
- **`daemon/control_socket.py`** — Unix domain socket for bidirectional communication with running tasks (JSON-line protocol)
- **`daemon/platform.py`** — PlatformAdapter interface (Darwin/Linux/Fallback) for idle detection, sleep/wake, notifications
- **`api/server.py`** — REST API + A2A gateway (`POST /a2a` + agent card at `GET /.well-known/agent.json`)

## Code Conventions

- Python 3.11+, all modules have `__all__` exports
- `mypy --strict` must pass (zero errors across 97 source files)
- `ruff check` must pass (D-rules enabled with google docstring convention)
- ConfigsLoader for config, dataclasses for internal data
- All I/O is async (`aiosqlite`, `asyncio.create_subprocess_exec`)
- No `print()` — use `logger_python` in library code, `rich.console` in CLI
- Line length: 100 (ruff + black)
- Max function length ~50 lines, max 5 params
- Early exit / guard clauses
- Domain-grouped directory structure
- All constants in `config/constants.py`, not scattered across modules
- Specific exception types (no broad `except Exception` that swallows)

## Testing Strategy

Requirements-Based Testing (RBT) with auto-generated RTM:
- Every test class tagged with `@pytest.mark.req("REQ-XX.X")`
- `scripts/req_coverage.py` generates the traceability matrix (scans Python + Playwright)
- Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`
- `pytest-asyncio` with `asyncio_mode = "auto"`
- Tests mirror src structure: `tests/agent/`, `tests/provider/`, etc.
- TDD enforced: tests written first (red), then implementation (green)
- 2303 tests total (1403 unit + 808 integration + 62 e2e + 14 Playwright E2E)
- 100% branch coverage
- 212/213 requirements covered (99.5%)
- All 497 req markers verified correct by independent audit

## Design Principles

1. **Reversibility governs everything** — planning, decisions, permissions calibrated by "how hard to undo?"
2. **Maximize autonomous progress** — user never the bottleneck unless truly irreversible
3. **Adapt to user presence** — attached: interactive. Detached: autonomous. Resource monitor drives this.
4. **Senior engineer mindset** — opinionated, documents rationale, asks only when genuinely stuck
5. **Three separate layers** — harness / behaviors / orchestration evolve independently
6. **Fix, log, and learn** — every mistake feeds the confidence-scored learning loop

## Autonomous Work Policy

When given autonomous work (user says "go", "continue", "don't stop"):
- **NEVER stop to report progress.** Keep working until truly finished.
- **Before claiming "done":** verify: are there pending subagents? unreviewed guidelines? unfixed violations? unrun tests? If YES → keep working.
- **After fixing violations:** re-run the review that found them to confirm they're actually fixed.
- **After implementing features:** run tests, check coverage, verify lint/types.
- **Commit and push frequently** — don't accumulate large uncommitted diffs.
- **If blocked** (needs user input, external service down): state the blocker clearly and stop. Otherwise keep going.

## Remote Ollama Setup

Development uses a remote Ollama instance on the LAN:
```bash
./scripts/remote-ollama-setup.sh --client 192.168.0.113
guild config --set provider.base_url=http://192.168.0.113:11434
```
