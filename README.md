# Guild

> Submission for the [Gemma 4 Developer Challenge](https://dev.to/devteam/join-the-gemma-4-challenge-3000-prize-pool-for-ten-winners-23in) | `#devchallenge` `#gemmachallenge` `#gemma`

**The problem:** Cloud-based AI coding agents (Copilot, Cursor, Claude Code) require paid APIs, constant attention, and hog system resources. You want an agent that works autonomously while you're away — without racking up costs.

**Guild** is a free, locally-focused autonomous coding agent harness built on **Gemma 4** models via Ollama.

### Why Gemma 4?

Guild's core insight: **most agent turns don't need a large model**. Reading a file, running a test, writing a simple function — a small model handles these fine. But complex reasoning requires escalation. Gemma 4's size tiers make this possible locally:

| Tier | Model | Role |
|------|-------|------|
| Fast | `gemma4-2b-edge-fast` | Simple ops — file reads, shell commands, quick code gen |
| Default | `gemma4-4b-dense-med` | Standard execution — most coding turns |
| Smart | `gemma4-26b-moe-agent` | Escalation target — complex reasoning, debugging stuck states |

The agent starts cheap and only escalates when stuck — giving you fast responses 80% of the time and deep reasoning when it actually matters.

## Features

- **Zero cost** — runs entirely on local Ollama/Gemma 4 models, no cloud API fees
- **Escalation chain** — fast model -> smart model -> CLI tools -> human (last resort)
- **"Good neighbor"** — detects user activity, throttles when you're working, runs full-speed when idle
- **Truly autonomous** — runs to completion, survives reboots and sleep/wake cycles
- **Self-improving** — extracts learnings from completed tasks, injects them into future sessions
- **Multi-agent teams** — decompose complex tasks into blocks, each running its own agent
- **Permission tiers** — nothing / ask / scoped / autopilot (with hardcoded-never safety layer)

## Quick Start

**Prerequisites:** Python 3.11+, [Ollama](https://ollama.com) with Gemma 4 models pulled.

```bash
# Pull Gemma 4 models
ollama pull gemma4-4b-dense-med
ollama pull gemma4-26b-moe-agent

# Clone and install
git clone https://github.com/LightShield/guild.git
cd guild
pip install -e .

# Initialize a project
guild init

# Configure your Ollama instance (defaults to localhost:11434)
guild config --set provider.base_url=http://localhost:11434
guild config --set provider.model=gemma4-4b-dense-med

# Run a task
guild task "Create a hello.txt file containing 'Hello from Guild'"

# Interactive chat
guild chat

# Background execution (works while you're away)
guild task "Refactor the auth module to use JWT tokens" --background
guild ps                    # see running tasks
guild attach <task_id>      # reconnect to a task
guild kill <task_id>        # stop a task
```

### Remote Ollama (LAN)

If Ollama runs on a different machine (e.g., a desktop GPU box):

```bash
# On the Ollama host: expose on LAN
OLLAMA_HOST=0.0.0.0 ollama serve

# On your dev machine: point Guild at it
guild config --set provider.base_url=http://<ollama-host-ip>:11434
```

## The Escalation in Action

```
[guild] Starting task with gemma4-4b-dense-med...
[guild] Turn 1: Reading auth module...
[guild] Turn 2: Planning refactor approach...
[guild] Turn 5: Stuck — repeated error in generated code
[guild] Escalating to gemma4-26b-moe-agent (reason: stuck_loop)
[guild] Turn 6: Analyzing error pattern...
[guild] Turn 7: Applying corrected implementation...
[guild] Turn 9: Running tests... all pass
[guild] Task completed. Learning extracted: "JWT migration requires updating middleware chain first"
```

## Real-World Example: Tinnitus Notch Therapy Player

My father has tinnitus — a condition causing a constant phantom tone. The treatment ([Tailor-Made Notched Music Training](https://en.wikipedia.org/wiki/Tinnitus#Sound-based_interventions)) removes the tinnitus frequency from music to suppress the phantom perception over time.

I had Guild build the player autonomously using a **coder + e2e verifier team**:

```bash
guild team -t music-builder "Create a Python music player with real-time notch filter..."
```

Guild's team (Gemma 4 4B coder + 26B verifier) iterated until the code passed both a DSP unit test and a live 3-second playback test — producing a working player that correctly attenuates a target frequency by 99% while preserving the rest of the audio.

See [`examples/music-player-poc/`](examples/music-player-poc/) for the full execution trace, block definitions, and generated code.

## Architecture

Three-layer design:

```
Layer 1 — Harness
├── Process lifecycle (daemon, sleep/wake, crash recovery)
├── Resource monitor (CPU throttling, "good neighbor")
├── Tools (file_read, file_write, shell, search, spawn_agent)
├── Storage (SQLite: tasks, messages, learnings, audit)
└── Permissions (4-tier + hardcoded-never)

Layer 2 — Agent Behaviors
├── Core loop (call model → execute tools → repeat)
├── Stuck detection (repeated errors, no-progress, loops)
├── Escalation chain (weak model → strong model → tools → human)
├── Self-review (adversarial check after task completion)
└── Learning extraction (confidence-scored insights)

Layer 3 — Orchestration
├── Team runner (multi-block task decomposition)
├── Message bus (agent-to-agent communication)
├── Agent spawner (sub-agents as tool calls)
└── Block definitions (TOML-based composable roles)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design decisions and [REQUIREMENTS.md](REQUIREMENTS.md) for the full specification.

## Status

**v0.2.0** — Core implementation complete.

- **108 source modules** across 20 domain-grouped packages
- **2308 tests** passing (unit + integration + E2E)
- **100% branch coverage**
- **213/213 requirements** with linked acceptance-criteria tests (100% traceability)
- `mypy --strict` — 0 errors
- `ruff` / `black` — fully clean
- Validated against real Ollama with all three Gemma 4 model tiers

## Development

```bash
pip install -e ".[dev]"             # install with dev dependencies
pytest                               # run all tests
pytest -m unit                       # fast unit tests only
pytest -m integration                # requires running Ollama
mypy src/guild/ --strict             # type check
ruff check src/ tests/               # lint
black src/ tests/                    # format
python scripts/req_coverage.py       # requirements traceability matrix
```

## License

[MIT](LICENSE)
