# Guild — Architecture Decisions

**Version:** 0.1.0
**Date:** 2026-05-03

This document captures architecture decisions that shape implementation but don't belong in the requirements spec.

---

## AD-01: Project / Workspace Model

A **project** is a directory with a `.guild/` folder — similar to how `.git/` works.

```
my-project/
├── .guild/
│   ├── guild.db            # SQLite database (single source of truth)
│   ├── config.toml         # Project-level config overrides
│   ├── blocks/             # Project-specific custom block definitions
│   ├── learnings/          # Extracted learnings (also in DB, files for readability)
│   └── artifacts/          # Agent-produced outputs, tracked by DB
├── src/                    # Your actual project files
└── ...
```

- `guild init` creates the `.guild/` directory in the current folder
- `guild status` shows current project info (like `git status`)
- The entry agent knows its project by the `.guild/` directory it was started in
- Global config lives in `~/.guild/config.toml` (defaults, provider settings, global block library)
- Project config overrides global config

---

## AD-02: Entry Agent Behavior

The entry agent is the **facilitator** — it routes work to the right blocks/agents rather than doing everything itself.

**Default system prompt** (single prompt for now, user-editable later):
- "You are the orchestrator for this project. Your job is to understand the user's request, break it down if needed, and delegate to the appropriate agents/blocks. If a team is configured, use it. If the task is simple enough to handle directly, do it yourself. Always verify completion against acceptance criteria before reporting done."

**Decision logic:**
1. Team configured? → Route through the team's block graph
2. No team, complex task? → Use planner block to decompose, then spawn workers
3. No team, simple task? → Do it directly (entry agent has basic tools: file read/write, shell, search)

**Configurable per-project** in `.guild/config.toml`:
```toml
[entry_agent]
system_prompt_file = "custom_prompt.md"  # override default
model = "llama3:70b"                      # override default model
team = "dev-loop"                         # default team to activate
tools = ["file_read", "file_write", "shell", "search", "spawn_agent"]
```

---

## AD-03: Concurrency Model

**Agents are async tasks within a single process** (not separate processes).

Rationale:
- Local Ollama with one GPU can only serve one inference at a time — separate processes would just queue
- Single process = easy shared state, no IPC complexity, simpler debugging
- Async tasks = agents can yield while waiting for model response, allowing interleaving
- SQLite WAL mode handles concurrent reads from async tasks fine

**Concurrency limit:** configurable, tied to model capacity.
```toml
[harness]
max_concurrent_agents = 1        # for single-GPU Ollama
max_concurrent_tool_calls = 4    # tools can run in parallel even if model is single-threaded
```

When `max_concurrent_agents = 1`: agents run in a cooperative round-robin. The active agent runs until it yields (waiting for model or tool), then the next queued agent gets a turn.

When using cloud providers (future): bump `max_concurrent_agents` higher since the bottleneck shifts to API rate limits.

---

## AD-04: Context Window Overflow Strategy

Local models have small context windows (8K-32K typical). Strategy when context grows too large:

```
1. MicroCompact (local trim, zero API calls)
   ↓ still too large?
2. AutoCompact (model-based summarization)
   ↓ still too large?
3. Context reset with structured handoff artifact
   ↓ task fundamentally needs more context than model supports?
4. Escalate to human: "This task needs more context than the current model
   supports (32K). Suggest switching to [larger model] or breaking the task
   into smaller pieces."
```

Triggers:
- MicroCompact: context reaches 70% of model's max
- AutoCompact: context reaches 85% of model's max
- Context reset: context reaches 95% after AutoCompact
- Human escalation: context reset artifact itself exceeds 50% of model's max

---

## AD-05: Internal Communication — Message Bus

Simple in-process message bus. No HTTP, no serialization overhead for local communication.

```
Interface:
  bus.send(target_agent_id, port_name, data: dict)
  bus.receive(agent_id) -> (port_name, data)
  bus.broadcast(data)  # to all agents in team
  bus.status(agent_id) -> AgentStatus
```

Messages are:
- Logged to SQLite (audit trail + replay)
- Typed by port type system (validated at send time)
- Queued per-agent (agent processes messages when it yields)

This is wrappable in A2A later by adding an HTTP gateway that translates A2A requests to bus messages.

---

## AD-06: Testing Strategy for the Harness

| Layer | Strategy |
|-------|----------|
| **Deterministic components** (storage, permissions, block graph validation, port type checking, message bus, config parsing) | Standard unit tests — no LLM needed |
| **Agent loop & tool execution** | Integration tests with **mocked LLM responses** — deterministic, fast, reproducible |
| **Session recording & replay** | Record real sessions (LLM calls + responses + tool results) and replay them for regression testing |
| **Block compositions** | Test that block graphs validate correctly, ports wire up, error propagation works — all without LLM |
| **End-to-end** | Small set of real LLM tests against Ollama with simple tasks — slow, run in CI nightly |

Key principle: **most harness code is deterministic and testable without an LLM.** The LLM is a single integration point behind the provider abstraction. Mock it for fast tests, use it for slow validation.
