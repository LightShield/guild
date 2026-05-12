# Guild — Requirements Specification

**Version:** 0.2.0
**Date:** 2026-05-07
**Author:** Or Magen

---

## Overview

A free, locally-focused agent harness that runs an autonomous coding agent against local models (Ollama). The core value: an agent that works while you're away and backs off when you're present — a "good neighbor" on your machine.

Designed to support long-running autonomous workflows with robust permission controls, background execution, and resource-aware scheduling. Provider-agnostic but Ollama-first.

---

## Priority Tiers

| Tier | Meaning | Target |
|------|---------|--------|
| **P0** | Get a single agent to work end-to-end | v0.1 |
| **P1** | Get the agent to run better | v0.2 |
| **P2** | Teams & blocks — multi-agent composition | v0.3 |
| **P3** | GUI & polish | v0.4+ |

---

## Architectural Insights (from Claude Code source analysis)

The following lessons are drawn from the Claude Code 512K-line TypeScript source leak (March 2026) and Anthropic's published harness design research. These should inform our architecture:

1. **The agent loop is dead simple — the harness is everything.** The core loop is a `while` loop: call model → if tool call, execute tool, append result, repeat. All complexity lives in the harness around it (context management, permissions, tools, error recovery). Don't overengineer the loop.

2. **Embed safety at the point of use.** Safety rules belong inside tool descriptions (where the model sees them at invocation time), not in a separate policy doc the model may "forget" during long conversations. Defense-in-depth: multiple layers of checks.

3. **Dedicated tools beat a generic shell.** Replace frequent shell commands with typed, permission-gated, auditable tools. Agents with 5-8 well-described purpose-built tools outperform agents with one omnibus tool.

4. **Context engineering is the competitive moat.** Separate static prompt content (cacheable) from dynamic content. Build multi-tier compression (local trim → model-based summarization → full compact with re-injection of critical state). Instrument what goes into the context window.

5. **Memory should be indexed hints, not trusted truth.** Lightweight index always loaded (<200 lines), detailed notes fetched on demand. Agent must verify memories against actual state before acting. Include "memory consolidation" during idle time.

6. **Multi-agent parallelism via cache sharing.** Sub-agents should share the parent's context/cache to avoid paying full token cost per worker. Use isolated execution environments (worktrees, containers) for parallel work. Sub-agent spawning is just another tool call — keep architecture flat.

7. **Use cheap models for cheap decisions.** Permission checks, safety screening, sentiment detection, context compression — use the smallest model (or regex/deterministic code) that can handle it. Reserve the strong model for reasoning and generation.

8. **Generator + Evaluator is a composable block pattern, not a hardcoded feature.** For complex tasks, separate the agent doing the work from the agent judging it. But this should be a reusable composite block (e.g., "verified-coder" = coder + evaluator), not baked into the autonomy system.

9. **Context resets > compaction for long tasks.** For very long runs, clearing context and starting a fresh agent with a structured handoff artifact can outperform in-place compaction (avoids "context anxiety" where models wrap up prematurely).

10. **Re-examine harness complexity with each model upgrade.** Every harness component encodes an assumption about what the model can't do alone. As models improve, strip scaffolding that's no longer load-bearing and add new pieces for newly-possible capabilities.

---

## Design Principles

These emerged from design review and govern all implementation decisions:

1. **Reversibility governs everything.** Planning depth, decision-making, permissions, execution approach — all calibrated by "how hard is this to undo?" Low-impact/reversible → just do it. High-impact/irreversible → think, test, get approval.

2. **Maximize autonomous progress.** The user is never the bottleneck unless it's truly irreversible. When blocked on one thing, work on another. Queue questions, don't block on them.

3. **Adapt to user presence.** Attached: interactive back-and-forth. Detached: full autonomy. The resource monitor's activity detection drives notification and interaction mode.

4. **Senior engineer mindset.** Opinionated, makes judgment calls, documents rationale. Asks only when genuinely uncertain, not for validation. Self-reviews adversarially.

5. **Three separate layers.** Layer 1 (Harness): process lifecycle, resource management, tools, storage, permissions. Layer 2 (Agent Behaviors): decision framework, self-review, learning, escalation. Layer 3 (Orchestration): teams, decomposition, multi-agent. Each evolves independently.

6. **Fix, log, and learn.** Every mistake feeds the confidence-scored learning loop. Fix immediately, log for review, extract a rule for future sessions.

---

## P0 — Get a Single Agent to Work End-to-End

### REQ-01: LLM Provider Abstraction

**Goal:** Run agents against local models (Ollama) today, with architecture that supports any provider tomorrow.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-01.1 | Unified LLM interface with a common request/response contract | Model-agnostic: same agent code works regardless of backend |
| REQ-01.2 | Ollama backend as the default and first-class provider | Must support streaming responses |
| REQ-01.3 | Provider configuration via config files (not hardcoded) | Endpoint URL, model name, parameters (temperature, max_tokens, etc.) |
| REQ-01.4 | Provider-specific prompt formatting handled transparently | Chat templates, system prompt handling differences |
| REQ-01.5 | Connection health checks and graceful error handling | Detect if Ollama is down, report clearly |

#### Acceptance Criteria (REQ-01.1 through REQ-01.5)

**REQ-01.1 — Unified LLM interface with a common request/response contract**

- AC-01.1.1: `Provider.generate()` returns `LLMResponse` with `content`, `tool_calls`, `input_tokens`, `output_tokens`, `model`
  - verify: Call `generate()` on any provider -> response has all 5 fields populated
- AC-01.1.2: `Provider.health_check()` returns `bool`
  - verify: Call `health_check()` -> returns `True` (reachable) or `False` (unreachable)
- AC-01.1.3: Any new provider implements the same interface
  - verify: Create a new provider subclass -> must implement `generate()` and `health_check()` or `TypeError`

**REQ-01.2 — Ollama backend as the default and first-class provider**

- AC-01.2.1: `OllamaProvider` is registered as the default when no provider is explicitly configured
  - verify: Load default config with no `[provider]` section -> `OllamaProvider` is selected
- AC-01.2.2: Streaming responses are supported and yield incremental tokens
  - verify: Call `generate()` with `stream=True` -> receive an async iterator of partial tokens that concatenate to the full response
- AC-01.2.3: Ollama-specific parameters (e.g., `num_ctx`, `num_gpu`) are forwarded correctly
  - verify: Set `num_ctx=4096` in config -> Ollama `/api/chat` request body includes `"num_ctx": 4096`

**REQ-01.3 — Provider configuration via config files (not hardcoded)**

- AC-01.3.1: Provider endpoint URL is read from config, not hardcoded
  - verify: Set `provider.base_url = "http://custom:11434"` in config -> provider connects to that URL
- AC-01.3.2: Model name is configurable per-project
  - verify: Set `provider.model = "gemma4:4b"` in config -> LLM calls use that model name
- AC-01.3.3: Generation parameters (temperature, max_tokens, top_p) are configurable
  - verify: Set `provider.temperature = 0.2` in config -> API call includes `"temperature": 0.2`
- AC-01.3.4: Invalid config values are rejected at startup with a clear error
  - verify: Set `provider.temperature = "banana"` -> startup fails with validation error naming the field and expected type

**REQ-01.4 — Provider-specific prompt formatting handled transparently**

- AC-01.4.1: System prompt is injected in the provider-appropriate position
  - verify: Send a message with a system prompt through `OllamaProvider` -> the Ollama API request places it in the `system` field (not as a user message)
- AC-01.4.2: Chat history is formatted per the provider's expected schema
  - verify: Send a multi-turn conversation through `OllamaProvider` -> messages array uses `role`/`content` pairs matching Ollama's `/api/chat` format
- AC-01.4.3: Tool call formatting is adapter-specific and transparent to the caller
  - verify: Define a tool and call `generate()` -> the tool schema is serialized in the provider's native format (Ollama JSON function calling schema) without the caller specifying format details

**REQ-01.5 — Connection health checks and graceful error handling**

- AC-01.5.1: `health_check()` detects an unreachable provider within the configured timeout
  - verify: Point provider at a non-existent host -> `health_check()` returns `False` within 5 seconds (default timeout)
- AC-01.5.2: Connection failure during `generate()` raises a typed exception, not a generic error
  - verify: Kill Ollama mid-request -> `generate()` raises `ProviderConnectionError` (not `Exception` or `ConnectionError`)
- AC-01.5.3: Transient failures are retried with backoff before surfacing to the agent loop
  - verify: Simulate one transient 503 followed by success -> `generate()` returns the successful response without the caller needing retry logic
- AC-01.5.4: A clear, human-readable message is logged when the provider is down
  - verify: Start Guild with Ollama stopped -> log output includes a message like "Cannot reach Ollama at http://localhost:11434 - is it running?"

### REQ-02: Cross-Platform Support (Windows, macOS, Linux)

**Goal:** Single codebase that works on all three major OSes. Windows is the primary development machine today.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-02.1 | All core functionality must be OS-agnostic | No platform-specific code in business logic |
| REQ-02.2 | Single install mechanism | `pip install` or a single install script |
| REQ-02.3 | File paths, process management, and networking must use cross-platform abstractions | pathlib, not string concatenation |
| REQ-02.4 | Platform-specific behavior (idle detection, sleep detection) behind a `PlatformAdapter` interface | Windows + macOS + Linux |

### REQ-03: Tiered Permission System

**Goal:** Granular, easy-to-switch permission levels that control what agents can do.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-03.1 | **Tier 0 — "Nothing"**: Agent can only think and respond, no tool use | Safe mode for testing prompts |
| REQ-03.2 | **Tier 1 — "Ask"**: Agent requests tool use, human approves per-tool | Approval granularity: once / per-session / per-call |
| REQ-03.3 | **Tier 2 — "Scoped"**: Agent can use all tools within a defined scope | Scope = directory tree, specific tool set, or resource pattern |
| REQ-03.4 | **Tier 3 — "Autopilot"**: All tools allowed, no approval needed | For trusted, long-running autonomous work |
| REQ-03.5 | Permission level switchable at runtime (CLI command or GUI toggle) | No restart required |
| REQ-03.6 | Audit log of all permission decisions | Who approved what, when |
| REQ-03.7 | **Hardcoded-never layer** — destructive/irreversible actions blocked regardless of tier | git push --force, rm -rf, history rewrite, money-spending API calls. Overridable only by explicit per-action flag |
| REQ-03.8 | **Reversibility principle** governs all permission decisions — the harder to undo, the more caution required | This is the universal governance rule across all tiers |

### REQ-05: CLI Interface

**Goal:** CLI is the complete, authoritative interface. Every operation is a CLI command.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-05.1 | **CLI is the primary interface** — every operation is a CLI command | Scriptable, pipe-friendly, automatable |
| REQ-05.2 | All agent interaction, monitoring, and config happens via CLI | Nothing requires a GUI |
| REQ-05.3 | Ability to send messages to the running agent from CLI | `guild chat` for interactive mode |
| REQ-05.4a | **Interactive attach** — `guild attach` allows sending messages to steer a running task, not just viewing | Challenge decisions, request tweaks, provide answers to queued questions |

### REQ-06: Autonomous Long-Running Operation ("Anti-Babysitting")

**Goal:** Agents run to completion without unnecessary human check-ins. They stop only when truly done or truly stuck.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-06.1 | Agents must not pause for confirmation unless genuinely blocked | No "shall I continue?" after every step |
| REQ-06.2 | Clear "done" criteria per task — agents self-verify completion | Run tests, check outputs, validate against spec |
| REQ-06.3 | Stuck detection — recognize when no progress is being made | Loop detection, repeated failures, resource exhaustion |
| REQ-06.4 | Graceful degradation on stuck — try alternatives before escalating | Retry with different approach, then escalate |
| REQ-06.5 | Human escalation only as last resort, with full context | "I tried X, Y, Z. Here's where I'm stuck. Here's what I need from you." |
| REQ-06.6 | Progress persistence — survive crashes, reboots, network drops | Checkpoint state to disk regularly |
| REQ-06.7 | Configurable autonomy timeout | "Run for max 4 hours, then pause and report" |
| REQ-06.8 | **Simple core loop** — while(true) { call model → execute tool → append result } | Per Claude Code: don't overengineer the control flow |
| REQ-06.9 | **Multi-turn conversation** — agent loop preserves message history between user inputs | `run()` appends to existing messages, does not reset. Enables `guild chat` and interactive attach |
| REQ-06.10 | **Adversarial self-review** — after tests pass, agent actively tries to break its own implementation | Look for edge cases, security holes, spec violations the tests might miss |
| REQ-06.11 | **Try-test-rollback for impactful decisions** — for non-trivial choices, try approach A, test it, rollback if it fails, try B | Only escalate to human if all approaches fail |
| REQ-06.12 | **Decision logging** — every non-trivial decision documented with rationale | Separate from audit log (which tracks tool calls). This tracks "why did I choose X over Y?" |

### REQ-08: Tool System

**Goal:** Built-in tools that are dedicated and typed (not a generic shell). MCP plugin architecture is P1.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-08.1 | Standard tool contract: name, description, input schema, execute() | Simple function interface |
| REQ-08.2 | **Dedicated typed tools over generic shell** — replace frequent shell commands with purpose-built tools | File read/write, code search, grep, glob — each with its own permissions and validation |
| REQ-08.3 | Built-in tools: file read/write, shell exec (with safety checks), search, glob | Ship with a useful default set; shell tool has embedded safety rules |
| REQ-08.4 | Tool usage audit log | Tool name, args, result, duration, which agent, approval status |
| REQ-08.5 | Tool timeout and resource limits | Prevent a single tool call from hanging the system |
| REQ-08.6 | Safety rules embedded in tool descriptions | Per Claude Code insight: model sees constraints at invocation time |
| REQ-08.7 | Shell command denylist — block dangerous patterns unless explicitly overridden | `rm -rf /`, `git push --force`, fork bombs, etc. |

### REQ-23: Background/Daemon Execution

**Goal:** Tasks run as background processes that survive terminal close. The user can launch, detach, reconnect, and stream logs.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-23.1 | `guild task "description" --background` launches the agent in a detached daemon process | CLI returns immediately after confirming launch |
| REQ-23.2 | Daemon writes PID to `.guild/run/<task_id>.pid` and state to SQLite | PID file enables kill, pause, status checks |
| REQ-23.3 | `guild attach <task_id>` reconnects to a running background task, streaming output in real-time | Reads from SQLite messages + notification channel (Unix socket or file-watch) |
| REQ-23.4 | `guild logs <task_id> [--follow]` streams agent output without interaction | Pure read-only log view. `--follow` tails new messages |
| REQ-23.5 | `guild ps` shows all running/paused/queued tasks with PIDs and elapsed time | Quick overview of what's happening |
| REQ-23.6 | Daemon process is a minimal supervisor: asyncio event loop, signal handling, crash recovery | Thin wrapper around existing `AgentLoop.run()` |
| REQ-23.7 | Multiple concurrent background tasks supported, subject to `max_concurrent_agents` config | Additional tasks queue; queue persisted in SQLite (survives reboot) |
| REQ-23.8 | Foreground mode (no `--background`) remains the default | No regression on interactive use |
| REQ-23.9 | Daemon uses a control socket (`.guild/run/guild.sock`) for control messages | Enables pause, resume, kill without PID signaling |

### REQ-24: Resource-Aware Scheduling ("Good Neighbor")

**Goal:** When the user is actively using their machine, Guild throttles or pauses inference. When idle, Guild runs at full speed.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-24.1 | Detect user activity state: `active` vs `idle` (no input for N minutes) | macOS: `CGEventSourceSecondsSinceLastEventType` or IOKit. Linux: `/proc/interrupts` delta or `xprintidle` |
| REQ-24.2 | Detect system load: CPU utilization, GPU utilization, memory pressure | macOS: `psutil`/`sysctl`. Linux: `/proc/stat`, `nvidia-smi` |
| REQ-24.3 | Three scheduling modes: `full` (no throttling), `polite` (yield on user activity), `stealth` (only run when idle) | Config: `[resource] mode = "polite"`. Default: `polite` |
| REQ-24.4 | `polite` mode: when user is active, delay between LLM calls (configurable backoff) | Reduces contention. Does NOT kill running inference — delays the NEXT one |
| REQ-24.5 | `stealth` mode: when user is active, pause all agent work. Resume after N minutes idle | For "run overnight" use cases |
| REQ-24.6 | GPU awareness: if VRAM is under pressure, Guild can unload the model or defer | Ollama-specific: `ollama ps` shows loaded models; can request unload |
| REQ-24.7 | Thermal awareness (macOS): if thermally throttled, reduce inference rate | Prevents fan spin-up during video calls |
| REQ-24.8 | `guild resource-status` shows current mode, system load, throttle state | Transparency — user understands why things are slow |
| REQ-24.9 | All thresholds configurable per-project and globally | `idle_timeout_minutes`, `cpu_threshold_percent`, `gpu_threshold_percent` |
| REQ-24.10 | Resource monitor runs as a lightweight thread in the daemon, polling every 5-10s | Minimal overhead |

### REQ-25: Process Lifecycle Management

**Goal:** Robust lifecycle — clean start, clean stop, crash recovery, external control.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-25.1 | `guild kill <task_id>` sends graceful shutdown to a running background task | Finish current tool call, save state, exit. Hard kill after 10s timeout |
| REQ-25.2 | `guild pause <task_id>` pauses a running task (no new turns start) | State persisted to SQLite. In-flight LLM call finishes but loop stops |
| REQ-25.3 | `guild resume <task_id>` resumes a paused task from last checkpoint | Reloads messages from SQLite, re-validates provider, continues loop |
| REQ-25.4 | Signal handling: SIGTERM/SIGINT → graceful shutdown, SIGUSR1 → checkpoint-and-continue | Standard Unix signal contract |
| REQ-25.5 | Crash recovery: detect orphaned PID files, offer `guild resume <task_id>` | Check if PID is alive. If not, mark task as `interrupted` |
| REQ-25.6 | State persisted on every turn boundary (not just graceful exit) | Already done via `storage.append_message()` per turn |
| REQ-25.7 | Stale lock detection: dead socket files are cleaned up automatically | Prevents "address already in use" after crashes |
| REQ-25.8 | `guild kill --all` stops all running Guild tasks in this project | Convenience for "stop everything now" |
| REQ-25.9 | Meaningful exit codes: 0=success, 1=task failed, 2=interrupted, 3=crash recovery available | Scriptable |

### REQ-26: Sleep/Wake Survival

**Goal:** Machine sleep does not corrupt agent state. Agent pauses cleanly on sleep, resumes on wake.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-26.1 | Detect system sleep and checkpoint before suspension | Time-drift detection (monotonic vs wall-clock) as MVP; OS notifications as enhancement |
| REQ-26.2 | On wake, detect sleep occurred and resume agent work | If `time.time() - last_turn_time >> expected`, sleep happened |
| REQ-26.3 | Ollama connection re-validated on wake (server may have died) | Health check before first post-wake inference. Retry with backoff |
| REQ-26.4 | In-flight LLM calls interrupted by sleep are retried, not treated as fatal | Network error from mid-stream interruption → retry the turn |
| REQ-26.5 | Sleep/wake events logged in audit trail | "why was agent stuck for 8 hours" → "machine slept 23:00–07:00" |
| REQ-26.6 | Configurable wake behavior: `resume` (default) or `stay-paused` | Some users want explicit `guild resume` after wake |

---

## P1 — Get the Agent to Run Better

### REQ-07: Context & Memory Management

**Goal:** Agents maintain useful context across sessions and share knowledge. Memory is indexed hints, not trusted truth.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-07.1 | Persistent conversation/task context across sessions | Stored on disk, survives restarts |
| REQ-07.2 | Checkpoint and resume for long-running tasks | Explicit checkpoints + auto-checkpoint on interval |
| REQ-07.3 | Shared knowledge base between team agents | Worker B can see what Worker A discovered |
| REQ-07.4 | **Multi-tier context compression** — local trim → model-based summarization → full compact with re-injection | MicroCompact (zero API calls) → AutoCompact → Full Compact |
| REQ-07.5 | **Skeptical memory** — agent verifies memories against actual state before acting | Memory entries are hints, not trusted facts |
| REQ-07.6 | Lightweight memory index always loaded, detailed notes fetched on demand | Index <200 lines |
| REQ-07.7 | Memory consolidation during idle time | Merge observations, remove contradictions |
| REQ-07.8 | **Context resets with structured handoff** for very long tasks | Clear context + handoff artifact |
| REQ-07.9 | Task history — browse and search past tasks and their outcomes | Queryable from CLI |
| REQ-07.10 | **Static/dynamic prompt separation** for cache efficiency | Static instructions cacheable, dynamic content separate |

### REQ-09: Long-Term Learning Loop

**Goal:** Guild gets smarter over time. Completed tasks are opportunities to extract knowledge.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-09.1 | **Post-task learning extraction** — learner reviews what happened after each task | What worked, failed, was slow, patterns emerged |
| REQ-09.2 | **Knowledge categories**: patterns, anti-patterns, tool tips, domain knowledge | Structured, not free-text dump |
| REQ-09.3 | **Confidence scoring** — learnings start tentative, get promoted after repeated validation | Prevents one-off flukes from becoming "knowledge" |
| REQ-09.4 | **Learning injection** — confirmed learnings available to agents in future sessions | Injected as hints |
| REQ-09.5 | **Learning review** — human can browse, edit, approve, or reject learnings | CLI; human stays in control |
| REQ-09.6 | **Cross-task learning** — patterns from task A inform task B | "Last time we did X, it worked well" |
| REQ-09.7 | **Block-level learning** — learnings scoped to specific blocks | "When using dev-loop, always lint first" |
| REQ-09.8 | **Learning decay** — old unvalidated learnings lose confidence | Prevents stale knowledge |
| REQ-09.9 | **Prompt refinement suggestions** — learner suggests improvements based on patterns | "The reviewer misses type errors — suggest adding X to prompt" |

### REQ-10: Cost & Resource Tracking

**Goal:** Know what your agents are consuming and set limits.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-10.1 | Token usage tracking per agent, per task, per session | Input tokens, output tokens, total |
| REQ-10.2 | Budget limits — max tokens, max time, max tool calls | Per-agent and per-task |
| REQ-10.3 | Resource summary in CLI | Real-time and historical |
| REQ-10.4 | Alerts when approaching limits | Configurable thresholds (80%, 90%, 100%) |
| REQ-10.5 | Cost estimation for cloud providers (when used) | Map tokens to approximate $ |

### REQ-11: Observability & Debugging

**Goal:** Full visibility into what agents are doing and why.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-11.1 | Full reasoning chain trace (not just final output) | Every LLM call, tool call, decision point |
| REQ-11.2 | Session replay from logs | Re-watch what happened step by step |
| REQ-11.3 | Structured logging with configurable levels | Debug, Info, Warn, Error |
| REQ-11.4 | Error recovery — restart crashed agents from last checkpoint | Automatic or manual |
| REQ-11.5 | Log export in standard formats (JSON, OpenTelemetry) | For external observability tools |

### REQ-12: Task Specification & Acceptance Criteria

**Goal:** Structured way to define what "done" means so agents can self-verify.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-12.1 | Task definition format with description, acceptance criteria, verification steps | YAML/TOML/Markdown |
| REQ-12.2 | Verification step execution — run tests, check files, validate output | Automated pass/fail |
| REQ-12.3 | Task decomposition tracking — see how orchestrator broke down a task | Tree view |
| REQ-12.4 | Task dependencies — "do B after A completes" | DAG-based scheduling |
| REQ-12.5 | Task status lifecycle: pending → in-progress → verifying → done/failed/blocked | Clear state machine |

### REQ-13: Security & Sandboxing

**Goal:** Protect the host system from runaway agent behavior.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-13.1 | Sandboxed execution for shell commands | Container, chroot, or OS-level sandboxing |
| REQ-13.2 | Network access controls per agent | Allow/deny internet, localhost only, etc. |
| REQ-13.3 | Secret management — agents use API keys without seeing raw values | Injected at runtime, masked in logs |
| REQ-13.4 | File system boundaries — agents can only access allowed paths | Enforced by Guild, not by convention |
| REQ-13.5 | Command allowlist/denylist | Block dangerous commands |

### REQ-14: Configuration as Code

**Goal:** Everything configurable via version-controlled files.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-14.1 | Agent definitions in config files (TOML) | Name, role, model, system prompt, tools, permissions |
| REQ-14.2 | Team compositions as named configs | "coding-team", "research-team", "solo-debug" |
| REQ-14.3 | Permission profiles as named configs | "safe", "dev-work", "full-auto" |
| REQ-14.4 | Environment-specific overrides | Dev vs. CI settings |
| REQ-14.5 | Config validation on startup | Fail fast with clear error messages |
| REQ-14.6 | Config hot-reload where possible | Change config without restart |

### REQ-15: Human-in-the-Loop Escalation Patterns

**Goal:** Smart escalation that doesn't block all work when one thing needs human input.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-15.1 | Asynchronous question queue — agent posts question, continues other work | Non-blocking escalation |
| REQ-15.2 | **Presence-aware notification** — when user is active, notify immediately; when idle/sleeping, queue silently | Tied to resource monitor's activity detection |
| REQ-15.3 | Escalation context — full history of what was tried before escalating | Human gets enough context to answer quickly |
| REQ-15.4 | Batch approval — review multiple pending requests at once | Efficient for returning after AFK |
| REQ-15.5 | Notification channels: desktop toast, terminal bell, webhook — configurable | Different channels for different presence states |

### REQ-16: Testing & Evaluation Framework

**Goal:** Measure and compare agent performance systematically.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-16.1 | A/B testing — same task, different models/configs, compare results | Side-by-side output comparison |
| REQ-16.2 | Benchmark suite — standard tasks for regression testing | Customizable per project |
| REQ-16.3 | Regression detection — alert when config changes degrade performance | Automated comparison against baseline |
| REQ-16.4 | Eval metrics — task completion rate, time, token usage, tool calls | Quantitative and qualitative |
| REQ-16.5 | Eval results stored and browsable | Historical trends |
| REQ-16.6 | **Progressive confidence building** — benchmarks → self-development → real projects | Trust in the system built incrementally through demonstrated capability |
| REQ-16.7 | **Self-development benchmark** — Guild can implement its own P1 features autonomously | If it can develop itself, it can develop other projects |

### REQ-27: Temporal Knowledge

**Goal:** Capture not just current code state but "why it was built this way" — the temporal aspect usually lost as developers change.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-27.1 | **Decision history** — key architectural and implementation decisions stored with context and rationale | Like DECISIONS.md but queryable by the agent |
| REQ-27.2 | **Present state + key past info** fetchable when relevant | Agent can ask "why is this module structured this way?" and get the historical answer |
| REQ-27.3 | Project-level instruction files (like .guild/prompt.md) consumed when they exist | Industry standard steering files — use them if present |
| REQ-27.4 | Learnings from past tasks injected as temporal context | "Last time we touched this module, X happened" |

### REQ-08 (extended): MCP Plugin Architecture

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-08.8 | **MCP-native tool interface** — tools are MCP servers or expose MCP-compatible schemas | Industry standard; enables reuse of existing MCP ecosystem |
| REQ-08.9 | Plugin-based tool loading — file-per-tool or directory-per-tool | Auto-discovery on startup |
| REQ-08.10 | Tool behavioral properties: `isConcurrencySafe`, `isReadOnly` | Enables optimization |
| REQ-08.11 | Tool result caching (optional, per-tool) | Avoid redundant expensive calls |

### REQ-17: Multi-Model Routing & Escalation

**Goal:** Use the right model for the right job. Escalate to smarter models when stuck, including external CLI tools.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-17.1 | Per-agent model assignment | Orchestrator = strong, workers = fast/cheap |
| REQ-17.2 | Fallback chains — if primary model is down/slow, use backup | Ollama → cloud, or large → small |
| REQ-17.3 | **Use cheap models for cheap decisions** | Permission checks, safety screening — smallest model that works |
| REQ-17.4 | Model capability tagging — match task requirements to model strengths | "needs code generation" → code-specialized model |
| REQ-17.5 | **Stuck-triggered escalation** — when stuck detector fires, automatically retry with next model in chain | Default chain: fast local → smart local → external CLI → human |
| REQ-17.6 | **External CLI tool as provider** — shell out to installed CLI tools (e.g., `gemini`, `claude`) as escalation providers | Parse text response; structured tool calling not required at this tier |
| REQ-17.7 | Escalation chain configurable per-project | `[escalation] chain = ["gemma4-4b", "gemma4-26b", "gemini-cli"]` |
| REQ-17.8 | **Malformed output recovery** — retry with correction hint, then escalate model, then exhaust chain, only then human | Retry 1-2x with "your response was malformed" hint before escalating |

### REQ-20: Rate Limiting & Backpressure

**Goal:** Prevent resource exhaustion when running many agents.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-20.1 | Rate limiting on LLM API calls | Per-provider, configurable |
| REQ-20.2 | Tool call queue with concurrency limits | Max N parallel shell commands |
| REQ-20.3 | Backpressure — pause low-priority agents when system is loaded | Priority-based scheduling |

---

## P2 — Teams & Blocks

### REQ-04: Multi-Agent Team Architecture & Composable Blocks

**Goal:** Entry agent (user-facing) that can spawn any agents, including other orchestrators. Flat, composable architecture — not a rigid hierarchy. Teams are built from reusable building blocks.

#### 4A: Core Agent Architecture

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.1 | **Entry agent is always the orchestrator** — every project starts with this agent as the user's interface | User always communicates with this base agent; it delegates |
| REQ-04.2 | The entry agent is present even in preset team compositions | Entry agent wires up the team and becomes point of contact |
| REQ-04.3 | Any agent can spawn other agents, including other orchestrators | No rigid hierarchy |
| REQ-04.4 | Agent spawning is just another tool call — keep architecture flat | No separate multi-agent runtime |
| REQ-04.5 | Worker agents that execute specific subtasks | Workers can be specialized |
| REQ-04.6 | **MCP for agent-to-tool communication** | Industry standard |
| REQ-04.7 | **Simple internal message bus for agent-to-agent communication** | `send(agent_id, port, data)` / `receive()` |
| REQ-04.7a | **A2A as optional external gateway (P3)** | For cross-Guild communication |
| REQ-04.8 | **Skills support** — agents can have pluggable skill definitions | Skill files that define capabilities |
| REQ-04.9 | Agent lifecycle management — spawn, monitor, pause, resume, kill | Guild manages all agent processes |
| REQ-04.10 | Shared context/workspace between team members | Cache sharing for token efficiency |
| REQ-04.11 | Dynamic worker spawning | Not limited to pre-defined team size |
| REQ-04.12 | **Git worktrees as isolation model** — each task gets its own worktree for true parallel file modification | Not just branches — separate working directories via `git worktree add` |
| REQ-04.13 | **Branching strategy** — agents merge freely to staging; main/release is gated by user review | Configurable policy: which branches are protected, which are free |
| REQ-04.14 | **Staging area** — a shared branch agents can merge to without user approval | Allows progress without blocking on review; user reviews staging → main merges in batch |
| REQ-04.15 | **Merge policy configurable per project** — auto-merge if tests pass, always require review, or trust level per branch | As user gains trust in system, gates can be relaxed |

#### 4B: Composable Agent Blocks

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.20 | **Atomic blocks** — single-agent building blocks with defined inputs/outputs/role | e.g., "coder", "reviewer", "planner" |
| REQ-04.21 | **Composite blocks** — groups of connected blocks saved as a single reusable unit | e.g., "verified-coder" = coder + evaluator |
| REQ-04.22 | **Block connectors** — defined input/output ports | Output of "coder" feeds into "reviewer" |
| REQ-04.23 | **Block library** — local catalog of available blocks | Built-in + user-created |
| REQ-04.24 | **CLI team composer** — text-based composition via config files | TOML graph description |
| REQ-04.25 | **Nesting** — composite blocks can contain other composite blocks | "dev-loop" inside "full-project" |
| REQ-04.26 | **Block versioning** — blocks are versioned; references pin a version | Default: pinned at composition time |
| REQ-04.27 | **Loop/cycle support in block graphs** | "coder → reviewer → coder" is valid; exit condition defined by evaluator |

#### 4B-i: Block Port Type System

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.30 | Every port has a **type tag** and optional **JSON schema** | Type tags: `plan`, `code-changes`, `review`, `test-results`, `text`, `any` |
| REQ-04.31 | Port compatibility checked at composition time | CLI: validation rejects with clear error |
| REQ-04.32 | `any` type is the escape hatch | For flexible blocks |
| REQ-04.33 | Composite blocks expose unconnected inner ports as their own ports | External interface derived from internal wiring |
| REQ-04.34 | New type tags can be registered by users | Extensible |
| REQ-04.35 | Port data is always serializable (JSON) | Enables persistence, logging, replay |

#### 4B-ii: Evaluator Contract & Exit Conditions

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.40 | **Standard evaluator output**: `{pass: bool, score: 0-100, feedback: string, details: {...}}` | All evaluators produce this shape |
| REQ-04.41 | **Each evaluator defines its own rubric/criteria** | Configurable per-instance |
| REQ-04.42 | **Loop exit checks `pass`** — loop continues until evaluator says `pass: true` | Score and feedback flow back to generator |
| REQ-04.43 | **Max iteration safety limit** per loop — configurable, default 5 | Prevents infinite loops |
| REQ-04.44 | **Evaluator criteria are part of the block config** — editable per-instance | Same type, different criteria |

#### 4B-iii: Error Propagation in Block Graphs

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.50 | **Block fails → retry N times** (configurable, default 1) | Transient failures handled locally |
| REQ-04.51 | **Still failing → escalate to caller** | Error includes what failed, what was tried |
| REQ-04.52 | **Caller decides**: retry differently, skip, substitute, or escalate further | Caller has autonomy |
| REQ-04.53 | **Error reaches entry agent with no resolution → escalate to human** | Last resort |
| REQ-04.54 | **Partial failure in parallel branches** — other branches continue | Don't kill the whole team |

#### 4C: Built-in Atomic Blocks

| Block | Role | Input Ports (type) | Output Ports (type) |
|-------|------|--------------------|---------------------|
| **planner** | Decomposes task into structured plan | `task: text` | `plan: plan` |
| **coder** | Writes code to spec | `spec: plan`, `context: files` | `changes: code-changes` |
| **reviewer** | Reviews code for correctness, style | `changes: code-changes`, `spec: plan` | `result: review` |
| **tester** | Writes and runs tests | `changes: code-changes`, `spec: plan` | `result: test-results` |
| **evaluator** | Judges quality against criteria | `artifact: any`, `criteria: text` | `result: review` |
| **researcher** | Reads docs, searches code | `question: text` | `report: text` |
| **writer** | Produces documentation | `topic: text`, `context: any` | `doc: document` |
| **learner** | Extracts lessons from completed work | `logs: any`, `outcomes: any` | `insights: learnings` |

#### 4D: Built-in Composite Blocks

| Composite Block | Composition | Loop? | Description |
|-----------------|-------------|-------|-------------|
| **verified-coder** | coder → evaluator | Yes | Code with built-in quality gate |
| **dev-loop** | planner → coder → tester → reviewer | Yes | Standard development cycle |
| **research-and-implement** | researcher → planner → verified-coder | No | Investigate first, then build |
| **dev-loop-with-learning** | dev-loop → learner | No | Dev cycle that captures lessons |


---

## P3 — GUI & Polish

### REQ-05 (extended): Web GUI

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-05.4 | CLI exposes a local REST API that a GUI consumes | GUI is purely a frontend |
| REQ-05.5 | **GUI** — web-based (localhost) real-time monitoring and interaction | Dashboard: agent status, tasks, output |
| REQ-05.6 | **Visual team composer** — drag-and-drop block editor | Node-based editor; equivalent to TOML configs |
| REQ-05.7 | GUI shows agent communication graph / message flow | Visual who's-talking-to-whom |

### REQ-18: Artifact Management

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-18.1 | Artifact collection — gather all outputs per task | Per-task artifact directory |
| REQ-18.2 | Diff view of codebase changes made by agents | Git-style diffs |
| REQ-18.3 | Accept/reject/edit agent outputs before committing | Review gate |
| REQ-18.4 | Artifact versioning — track iterations | "Draft 1, Draft 2, Final" |
| REQ-18.5 | Artifact export | Zip, git bundle, etc. |

### REQ-19: Session & Workflow Templates

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-19.1 | Save a workflow as a reusable template | "Do code review like last time" |
| REQ-19.2 | Parameterized templates | Template variables |
| REQ-19.3 | Import/export/share templates | File-based, versionable |

### REQ-21: Offline-First Design

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-21.1 | Core functionality works with zero internet | Ollama + local tools = fully functional |
| REQ-21.2 | Cloud features degrade gracefully | Clear error, automatic fallback to local |
| REQ-21.3 | Local model management from Guild | `guild models list`, `guild models pull` |
| REQ-21.4 | Offline documentation | `guild help <topic>` |

### REQ-22: RPG Fun Mode (UI Theme)

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-22.1 | **UI mode toggle**: "serious" (default) and "RPG" mode | `guild config set ui.mode rpg` |
| REQ-22.2 | RPG mode renames concepts in the UI only | Tasks → Quests, Teams → Parties, etc. |
| REQ-22.3 | RPG-style progress indicators | XP bars, "Level Up!" |
| REQ-22.4 | Quest log view for task history | RPG-style quest tracker |
| REQ-22.5 | Agent "character sheets" | Model, tools, stats |
| REQ-22.6 | Fun notifications | "A new quest has arrived!" |

### REQ-04.24 (extended): Visual Team Composer in GUI

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.24a | Drag-and-drop blocks, connect them, save as team config | Node-RED / Unreal Blueprints style |

---

## Cross-Cutting Concerns

These apply across all requirements:

| Concern | Requirement |
|---------|-------------|
| **Logging** | All components use structured logging with consistent format |
| **Error handling** | All errors are caught, logged, and surfaced clearly — no silent failures |
| **Testing** | All components have unit tests; integration tests with mocked LLM; session recording/replay for regression |
| **Documentation** | All public APIs, config formats, and tool interfaces are documented |
| **Performance** | Response latency targets: CLI commands < 200ms, agent message relay < 100ms |
| **Backwards compatibility** | Config format changes are versioned; old configs produce migration instructions |

### Unified Storage Architecture

**Single source of truth: SQLite database** with files on disk for large artifacts.

| Data | Storage | Notes |
|------|---------|-------|
| Agent state & context | SQLite | Conversation history, current state, checkpoints |
| Memory & learnings | SQLite | Index, confidence scores, categories, decay timestamps |
| Audit logs | SQLite | Tool calls, permission decisions, agent actions |
| Task history | SQLite | Definitions, status, outcomes |
| Daemon state | SQLite + PID files | PID, socket path, status, queue position |
| Block definitions | SQLite + files | Metadata in DB, config files on disk |
| Team compositions | SQLite + files | Metadata in DB, config files on disk |
| Artifacts (code, docs) | Files on disk, tracked in SQLite | DB stores path, hash, metadata |
| Session traces | SQLite | Full reasoning chains for replay |
| Config | Files on disk | TOML, read on startup, hot-reloaded |

---

## Glossary

| Term | Definition |
|------|------------|
| **Guild** | The core runtime that manages agents, tools, permissions, and communication |
| **Agent** | An LLM-powered entity with a role, tools, and permissions |
| **Entry Agent** | The user-facing agent — first point of contact; can delegate |
| **Orchestrator** | An agent role that decomposes tasks and delegates to workers |
| **Worker** | An agent that executes specific subtasks |
| **Block (Atomic)** | A single-agent building block with defined inputs, outputs, and role |
| **Block (Composite)** | A group of connected blocks saved as a reusable unit |
| **Block Library** | The catalog of available blocks (built-in + user-created) |
| **Connector** | Input/output port definition for block wiring |
| **Tool** | A capability an agent can invoke (file read, shell exec, etc.) |
| **MCP** | Model Context Protocol — standard for agent-to-tool communication |
| **A2A** | Agent-to-Agent Protocol — optional for cross-Guild communication |
| **Message Bus** | Internal agent-to-agent communication — send/receive, no network overhead |
| **Skill** | A pluggable capability definition |
| **Team** | A configured graph of connected blocks working together |
| **Session** | A single run of a task, from start to completion |
| **Checkpoint** | A saved snapshot of agent/task state for resume |
| **Profile** | A named configuration (permission, team, etc.) |
| **Learning** | An extracted insight stored with confidence score |
| **Daemon** | The background process that runs the agent loop when detached from the terminal |
| **Good Neighbor** | Resource-aware scheduling that yields to user activity |
