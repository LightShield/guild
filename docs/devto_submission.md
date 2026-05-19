---
title: Guild — A Free Autonomous Coding Agent That Escalates Through Gemma 4 Models
published: false
tags: devchallenge, gemmachallenge, gemma
---

*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/devteam/join-the-gemma-4-challenge-3000-prize-pool-for-ten-winners-23in)*

## What I Built

**Guild** is a free, locally-running autonomous coding agent that works while you're away and backs off when you're present.

The problem: cloud-based AI coding agents (Copilot, Cursor, Claude Code) require paid APIs, constant babysitting, and hog your machine. I wanted an agent that:

- Runs for free on local hardware
- Works autonomously on tasks without me watching
- Knows when I'm using the machine and throttles itself
- Gets smarter over time by learning from its own mistakes

Guild solves this with an **escalation-first architecture**: start with the cheapest Gemma 4 model, and only move up when the agent gets stuck. Most tasks don't need the biggest model — but when they do, the system adapts automatically.

### Key Features

- **Escalation chain**: Gemma 4 4B Dense (`gemma4-4b-dense-med`) → Gemma 4 26B MoE (`gemma4-26b-moe-agent`) → CLI tools → human (last resort)
- **Visual flow composer**: drag-and-drop web UI to design multi-agent workflows, save reusable blocks, expand to inspect internals
- **"Good neighbor" mode**: detects user activity via CPU/input monitoring, throttles to zero when you're working, runs full-speed when idle
- **Truly autonomous**: survives reboots, sleep/wake cycles, crashes — picks up where it left off
- **Self-improving**: extracts learnings from completed tasks, injects them into future sessions
- **Multi-agent teams**: decompose complex tasks into blocks, each running its own Gemma 4 instance
- **Permission tiers**: nothing / ask / scoped / autopilot — with a hardcoded-never safety layer

## Demo

<!-- Record with: asciinema rec demo.cast -c "guild task 'Build a REST API with auth middleware'" -->
<!-- Then upload to asciinema.org and paste the embed link below -->
<!-- Or record a screen capture of the Web UI flow composer + terminal side by side -->

> **Live demo:** Guild autonomously builds code using Gemma 4, escalating from the fast 4B model to the 26B MoE model when stuck.
> 
> The web UI shows the flow composer where you can visually design multi-agent teams.

```bash
# Install and initialize
pip install -e ".[dev]"
guild init

# Configure Gemma 4 escalation chain
guild config --set provider.model=gemma4-4b-dense-med
guild config --set escalation.escalation_chain=gemma4-26b-moe-agent

# Run a task — watch it escalate when needed
guild task "Refactor the auth module to use JWT tokens instead of sessions"

# Or run in background while you work
guild task "Add comprehensive error handling to the API layer" --background
guild ps  # check progress anytime
```

### The Escalation in Action

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

## Code

**Repository:** [github.com/LightShield/guild](https://github.com/LightShield/guild)

### Architecture (3 layers)

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

### Web UI — Visual Flow Composer

Guild includes a web-based flow composer (`guild serve`) for designing multi-agent teams visually:

- **Dark-mode canvas** powered by xyflow — drag agents from palette, connect with edges
- **Reusable blocks** — multi-select agents, save as a named block, drag it back as a single node
- **Inline expansion** — click a block to expand it on the canvas showing internal nodes and dashed connection lines
- **Verifier decorators** — attach approval loops to any agent (loop until verifier passes, max N iterations)
- **Preset flows** — one-click "Full Development" loads a complete requirements→architecture→TDD→review→verification pipeline

### Stats

- **108 source modules** across 20 domain-grouped packages
- **2307 tests** (unit, integration, E2E + Playwright)
- **100% branch coverage**
- **213 requirements** with full acceptance criteria traceability
- Pure Python 3.11+, async throughout, zero cloud dependency

## How I Used Gemma 4

### Model Selection: Why Gemma 4?

Gemma 4 is the ideal model family for Guild because:

1. **Runs locally via Ollama** — zero API cost, complete privacy
2. **Multiple size tiers** — enables the escalation architecture
3. **128K context window** — can hold entire codebases in context
4. **Strong code reasoning** — particularly the 26B MoE agent variant

### The Escalation Architecture

The core insight: **most agent turns don't need a 31B model**. Reading a file, running a test, writing a simple function — Gemma 4 4B handles these fine. But when the agent encounters:

- Repeated failures (same error 3+ times)
- Complex multi-file reasoning
- Architectural decisions requiring broad context

...it automatically escalates to Gemma 4 26B MoE, which has the reasoning depth to break through. This gives you:

- **80% of turns** at 4B speed (fast, low resource usage)
- **20% of turns** at 26B quality (when it actually matters)
- **Near-zero cost** compared to cloud API pricing

### Model Variants Used

| Tier | Ollama Model | Params | Role |
|------|-------------|--------|------|
| Edge | `gemma4-2b-edge-fast` | 5.1B (Q4) | Ultra-light routing, permission checks |
| Fast | `gemma4-4b-dense-med` | 8.0B (Q4) | Default execution — file ops, shell commands, simple code generation |
| Smart | `gemma4-26b-moe-agent` | 25.8B (Q4) | Escalation target — complex reasoning, architecture decisions, debugging stuck states |

### Why Not Just Use the Big Model?

Three reasons:
1. **Resource contention** — 26B MoE uses significant RAM/VRAM. The "good neighbor" philosophy means minimizing resource usage.
2. **Speed** — 4B responds in 1-2 seconds; 26B takes 10-15 seconds. For simple file reads, that latency is wasted.
3. **Autonomy duration** — when running overnight on a coding task, token efficiency means more work done per charge cycle.

The escalation chain is configurable. If you have the hardware, run 26B all the time. If you're on a laptop, start at 4B and let Guild decide when to bring in the heavy model.

---

*Guild is open source, free forever, and designed to make AI coding agents accessible to everyone — not just those with API budgets.*
