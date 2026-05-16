# Guild

**The problem:** Existing AI coding agents (Copilot, Cursor, Claude Code) require paid cloud APIs, constant attention, and hog system resources. You want an agent that works autonomously on tasks while you're away — without racking up API costs.

**Guild** is a free, locally-focused agent harness that runs autonomous coding agents against local models (Ollama).

What makes it different:

- **Zero cost** — runs entirely on local Ollama models, no cloud API fees ever.
- **"Good neighbor"** — automatically throttles when you're using the machine, runs at full speed when idle.
- **Truly autonomous** — runs to completion without babysitting, survives reboots and sleep/wake cycles.
- **Self-improving** — extracts learnings from completed tasks and gets smarter over time.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Initialize a project
guild init

# Configure your Ollama instance
guild config --set provider.base_url=http://localhost:11434
guild config --set provider.model=gemma4-4b-dense-med

# Run a task
guild task "Create a hello.txt file containing 'Hello from Guild'"

# Interactive chat
guild chat

# Background execution
guild task "Implement feature X" --background
guild ps                    # see running tasks
guild attach <task_id>      # reconnect to a task
guild kill <task_id>        # stop a task
```

## Features

- **Local-first** — Ollama as default backend, zero cloud dependency, free to run
- **Good neighbor** — throttles when you're using the machine, runs at full speed when idle
- **Autonomous** — runs to completion without babysitting, stops only when truly stuck
- **Escalation chain** — fast model → smart model → external CLI tools → human (only as last resort)
- **Permission tiers** — nothing / ask / scoped / autopilot (with hardcoded-never safety layer)
- **Persistent** — survives crashes, reboots, sleep/wake cycles
- **Self-improving** — extracts learnings from completed tasks, gets smarter over time

## Architecture

Three-layer design:
1. **Harness** (Layer 1) — process lifecycle, resource management, tools, storage, permissions
2. **Agent Behaviors** (Layer 2) — decision framework, self-review, learning, escalation
3. **Orchestration** (Layer 3) — teams, task decomposition, multi-agent coordination

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design decisions and [REQUIREMENTS.md](REQUIREMENTS.md) for the full specification.

## Status

**v0.2.0** — Core implementation complete. 712 tests (708 unit + 4 integration).

| Tier | Coverage |
|------|----------|
| P0 (single agent) | 66/73 (90%) |
| P1 (run better) | 75/76 (99%) |
| P2 (teams & blocks) | 38/39 (97%) |
| P3 (GUI & polish) | 19/22 (86%) |

Validated against real Ollama (gemma4 models) — single-step and multi-step tasks complete successfully.

## Development

```bash
pytest                          # run all tests
pytest -m unit                  # fast unit tests only
pytest -m integration           # requires running Ollama
python scripts/req_coverage.py  # requirements traceability matrix
ruff check src/ tests/          # lint
black src/ tests/               # format
```

## License

Private — personal use.
