---
title: Guild — A Free Autonomous Coding Agent That Escalates Through Gemma 4 Models
published: false
tags: devchallenge, gemmachallenge, gemma
---

*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

## What I Built

**Guild** is a free, locally-running autonomous coding agent that works while you're away and backs off when you're present.

The problem: cloud-based AI coding agents (Copilot, Cursor, Claude Code) require paid APIs, constant babysitting, and hog your machine. I wanted an agent that:

- Runs for free on local hardware
- Works autonomously on tasks without me watching
- Knows when I'm using the machine and throttles itself
- Gets smarter over time by learning from its own mistakes

Guild solves this with an **escalation-first architecture**: start with the cheapest Gemma 4 model, and only move up when the agent gets stuck. Most tasks don't need the biggest model — but when they do, the system adapts automatically.

### Key Features

- **Escalation chain**: Gemma 4 E4B → Gemma 4 31B Dense → CLI tools → human (last resort)
- **Visual flow composer**: drag-and-drop web UI to design multi-agent workflows, save reusable blocks, expand to inspect internals
- **"Good neighbor" mode**: detects user activity via CPU/input monitoring, throttles to zero when you're working, runs full-speed when idle
- **Truly autonomous**: survives reboots, sleep/wake cycles, crashes — picks up where it left off
- **Self-improving**: extracts learnings from completed tasks, injects them into future sessions
- **Multi-agent teams**: decompose complex tasks into blocks, each running its own Gemma 4 instance
- **Permission tiers**: nothing / ask / scoped / autopilot — with a hardcoded-never safety layer

## Demo

### Design → Run → Monitor (all in one UI)

Guild's web interface lets you design multi-agent workflows visually, then run them with one click:

**1. Composer Studio — Design your agent team:**

![Flow Composer showing Python Dev Loop with expanded TDD block](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/flow-composer-expanded.jpeg)

The "Python Dev Loop" preset: requirements→architect feed into verifiers, which gate a `tdd_implementer` block. Click to expand that block and see the internal pipeline (planner→test_writer→implementer→refactorer). The edit panel on the right shows agent configuration — name, role, Gemma 4 model selection, instructions, and ports.

![Composer Studio with live execution status](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/composer-live-execution.jpeg)

Same composer, now running a live workflow: "write me a hello app in assembly 8086". The planner block completed, coder is currently executing. Status badges update in real-time.

**2. Workflow Execution — Watch blocks run in sequence:**

![Workflow detail view showing planner completed with assembly code output, coder running](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/workflow-detail.jpeg)

The planner agent (powered by Gemma 4) decomposed the task and produced assembly instructions. The coder block is now executing those instructions. Each block's output is visible in real-time, with a timeline showing the full execution history.

**3. Task Management — Launch and monitor agents:**

![Tasks view showing running workflow blocks with status badges](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/tasks-view.jpeg)

Launch workflows or individual agents from the UI. Filter by status, inspect execution details, stop running tasks.

### "Good Neighbor" Mode — Resource Awareness

Guild detects when you're using the machine and throttles itself:

| Without Good Neighbor | With Good Neighbor |
|---|---|
| ![Ollama using 10GB RAM, 87% memory](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/without-good-neighbor.jpeg) | ![Ollama using 7.5GB RAM, 69% memory](https://raw.githubusercontent.com/LightShield/guild/main/docs/images/with-good-neighbor.jpeg) |
| Ollama consumes 10.2 GB, system at 87% memory | Throttled down — 7.5 GB, system at 69% memory |

When you're gaming, browsing, or coding — Guild backs off automatically. When you're away, it ramps back up.

### CLI — For When You Prefer the Terminal

```bash
# Install and initialize
pip install -e ".[dev]"
guild init

# Configure Gemma 4 escalation chain
guild config --set provider.model=gemma4-e4b
guild config --set escalation.escalation_chain=gemma4-31b-dense

# Run a task — watch it escalate when needed
guild task "Refactor the auth module to use JWT tokens instead of sessions"

# Or run in background while you work
guild task "Add comprehensive error handling to the API layer" --background
guild ps  # check progress anytime
```

### Real Example: Tinnitus Therapy Music Player

My father has tinnitus. One treatment is "notched music" — removing the phantom frequency from music over time. I had Guild build the player instead of doing it myself.

**Team:** Gemma 4 E4B (coder) + Gemma 4 31B Dense (verifier)

```
Iteration 1:
  [coder/E4B]     Wrote music_player.py (7455 chars)
                  — real-time IIR notch filter via scipy.signal
                  — sounddevice OutputStream callback
                  — keyboard thread for live frequency control
  [verifier/31B]  Running verification:
                  ✓ Files exist
                  ✓ Syntax valid
                  ✗ FAIL: lfilter called with wrong argument order
                    (data passed before coefficients)

Iteration 2:
  [coder/E4B]     Fixed lfilter call order, added zi state persistence
  [verifier/31B]  Running verification:
                  ✓ Files exist
                  ✓ Syntax valid
                  ✓ API usage correct (iirnotch + lfilter + lfilter_zi)
                  ✓ 3-second playback test — no errors
                  PASS (score: 90)

[guild] Team completed. Learning: "lfilter(b, a, x, zi=zi) — coefficients first, not data"
```

The verifier caught a subtle API misuse that would have caused silent audio corruption. Without the verification loop, the bug ships. With it, the coder gets specific feedback and fixes it in one turn.

Full source + execution trace: [`examples/music-player-poc/`](https://github.com/LightShield/guild/tree/main/examples/music-player-poc)

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

- **106 source modules** across 20 domain-grouped packages
- **2383 Python tests** + **246 Playwright E2E tests** (2629 total)
- **100% branch coverage** on Python code
- **213 requirements** with full acceptance criteria traceability
- **0 semantic lies** — all tests adversarially verified for honesty
- Pure Python 3.11+, async throughout, zero cloud dependency
- Built using a self-improving development system with gated flows (see [Guidelines](https://github.com/LightShield/Guidelines))

## How I Used Gemma 4

### Model Selection: Why Gemma 4?

Gemma 4 is the ideal model family for Guild because:

1. **Runs locally via Ollama** — zero API cost, complete privacy
2. **Multiple size tiers (E2B, E4B, 31B Dense)** — enables the escalation architecture
3. **128K context window** — can hold entire codebases in context
4. **Strong code reasoning** — particularly the 31B Dense variant

### The Escalation Architecture

The core insight: **most agent turns don't need the 31B Dense model**. Reading a file, running a test, writing a simple function — Gemma 4 E4B handles these fine. But when the agent encounters:

- Repeated failures (same error 3+ times)
- Complex multi-file reasoning
- Architectural decisions requiring broad context

...it automatically escalates to Gemma 4 31B Dense, which has the reasoning depth to break through. And if even that isn't enough — the chain continues to cloud providers (Claude, Codex) as a final tier before asking a human.

This gives you:

- **80% of turns** at E4B speed (fast, local, free)
- **15% of turns** at 31B Dense quality (complex local reasoning)
- **5% of turns** at cloud tier (when local models genuinely can't solve it)
- **Near-zero cost** — cloud is only used as last resort

### The Full Escalation Chain

| Tier | Provider | Model | When |
|------|----------|-------|------|
| 1 | Ollama (local) | **Gemma 4 E2B** | Routing, permission checks, trivial ops |
| 2 | Ollama (local) | **Gemma 4 E4B** | Default — file ops, shell, simple code |
| 3 | Ollama (local) | **Gemma 4 31B Dense** | Complex reasoning, architecture, debugging |
| 4 | Cloud | **Claude / Codex** | When local models are stuck (3+ failures) |
| 5 | Human | — | Truly irreversible decisions only |

Teams can also mix providers per-block — e.g., Gemma 4 E4B as the fast coder, Claude as the strict reviewer. Each block in a workflow defines its own provider independently.

```bash
# Configure the escalation chain
guild config --set provider.provider_name=ollama
guild config --set provider.model=gemma4-4b-dense-med
guild config --set escalation.escalation_chain=gemma4-31b-dense,claude
```

### Why Not Just Use the Big Model?

Three reasons:
1. **Resource contention** — 31B Dense uses significant RAM/VRAM. The "good neighbor" philosophy means minimizing resource usage.
2. **Speed** — E4B responds in 1-2 seconds; 31B Dense takes 10-15 seconds. For simple file reads, that latency is wasted.
3. **Autonomy duration** — when running overnight on a coding task, token efficiency means more work done per charge cycle.

The escalation chain is configurable. If you have the hardware, run 31B Dense all the time. If you're on a laptop, start at E4B and let Guild decide when to bring in the heavy model. If you need cloud power for the hardest problems, add Claude/Codex to the chain — Guild will only use them when local models are genuinely stuck.

---

*Guild is open source, free forever, and designed to make AI coding agents accessible to everyone — not just those with API budgets.*
