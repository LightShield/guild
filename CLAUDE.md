# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Guild is a locally-focused agent harness for running LLM-powered agent teams. It uses Ollama as the default LLM backend and manages agent execution, permissions, tool use, and team composition through a CLI. Early development — v0.1.0.

## Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest                                    # all tests
pytest -m unit                            # fast unit tests only
pytest -m integration                     # integration tests
pytest tests/test_agent.py                # single file
pytest tests/test_agent.py::TestExecuteTool::test_file_read  # single test

# Linting and formatting
ruff check src/ tests/                    # lint
ruff check --fix src/ tests/             # auto-fix
black src/ tests/                         # format

# Type checking
mypy src/

# Run the CLI
guild --help
guild init                                # initialize .guild/ in current dir
guild task "description"                  # run a task
guild chat                                # interactive chat
guild status                              # project status
guild serve                               # start web GUI on :8585
```

## Architecture

**Single-process async model.** Agents are async tasks (not separate processes) coordinated by an in-process message bus. SQLite (WAL mode) is the single source of truth for all state.

### Key Layers

- **`src/guild/core/`** — The engine: agent loop, message bus, storage, permissions, config, context compression, stuck detection, rate limiting
- **`src/guild/providers/`** — LLM abstraction (`LLMProvider` base class in `base.py`, Ollama implementation in `ollama.py`, model routing in `router.py`)
- **`src/guild/blocks/`** — Block system: atomic blocks (planner, coder, reviewer, tester, evaluator, researcher) and team composition via `BlockRegistry`
- **`src/guild/cli/`** — Typer CLI (`main.py` is the single entry point, all commands in one file)
- **`src/guild/api/`** — FastAPI server for the web GUI

### Core Concepts

- **Block** (`BlockDef`): An agent template — system prompt, tools, ports, permission tier
- **Team** (`TeamDef`): A graph of block instances connected via typed ports, with optional loops (generator/evaluator pairs)
- **AgentLoop**: The core while-loop — call model → execute tools → repeat. Integrates MicroCompact (context compression), StuckDetector, RateLimiter, ToolQueue
- **Permission tiers**: `nothing` → `ask` → `scoped` → `autopilot`
- **Storage**: All state in `.guild/guild.db` — tasks, agents, messages, audit log, learnings

### Data Flow

`CLI command` → `load_config()` → `create_provider()` → `AgentLoop` or `TeamRunner` → tool calls via `execute_tool()` → results stored in SQLite

## Code Conventions

- Python 3.11+, all modules have `__all__` exports
- Pydantic models for data (`core/models.py`), dataclasses for internal results (`ToolResult`)
- All I/O is async (`aiosqlite`, `asyncio.create_subprocess_shell`)
- No `print()` — use `logging` in library code, `rich.console` in CLI
- Line length: 100 (ruff + black)
- Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`
- `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions work without decorator

## Testing Strategy

Most harness code is deterministic and testable without an LLM. The LLM is mocked via `AsyncMock` returning `LLMResponse` objects. Tests use `tmp_path` for filesystem isolation and in-memory SQLite for storage.
