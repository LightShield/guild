# Agent Harness — Requirements Specification

**Version:** 0.1.0
**Date:** 2026-05-03
**Author:** Or Magen

---

## Overview

A locally-focused, cross-platform agent harness that enables running LLM-powered agent teams with full autonomy, observability, and control. Designed to work primarily with local models (Ollama) while remaining provider-agnostic, and to support long-running autonomous workflows with robust permission controls.

---

## Priority Tiers

| Tier | Meaning | Target |
|------|---------|--------|
| **P0** | MVP — must have for first usable version | v0.1 |
| **P1** | Important — needed for real daily use | v0.2 |
| **P2** | Nice-to-have — adds polish and power | v0.3+ |

---

## P0 — MVP Requirements

### REQ-01: LLM Provider Abstraction

**Goal:** Run agents against local models (Ollama) today, with architecture that supports any provider tomorrow.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-01.1 | Unified LLM interface with a common request/response contract | Model-agnostic: same agent code works regardless of backend |
| REQ-01.2 | Ollama backend as the default and first-class provider | Must support streaming responses |
| REQ-01.3 | Provider configuration via config files (not hardcoded) | Endpoint URL, model name, parameters (temperature, max_tokens, etc.) |
| REQ-01.4 | Provider-specific prompt formatting handled transparently | Chat templates, system prompt handling differences |
| REQ-01.5 | Connection health checks and graceful error handling | Detect if Ollama is down, report clearly |

### REQ-02: Cross-Platform Support (Windows, macOS, Linux)

**Goal:** Single codebase that works identically on all three major OSes. Installation is a single script.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-02.1 | All core functionality must be OS-agnostic | No platform-specific code in business logic |
| REQ-02.2 | Single install script per platform (or one universal script) | `install.sh` / `install.ps1` or a single cross-platform installer |
| REQ-02.3 | Single update mechanism | `agent-harness update` or equivalent |
| REQ-02.4 | No hard dependencies on platform-specific tools | If a tool is needed (e.g., shell), abstract it behind a platform adapter |
| REQ-02.5 | File paths, process management, and networking must use cross-platform abstractions | Use language-native path handling, not string concatenation |
| REQ-02.6 | CI testing on all three platforms | GitHub Actions or equivalent matrix builds |

### REQ-03: Tiered Permission System

**Goal:** Granular, easy-to-switch permission levels that control what agents can do.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-03.1 | **Tier 0 — "Nothing"**: Agent can only think and respond, no tool use | Safe mode for testing prompts |
| REQ-03.2 | **Tier 1 — "Ask"**: Agent requests tool use, human approves per-tool | Approval granularity: once / per-session / per-call |
| REQ-03.3 | **Tier 2 — "Scoped"**: Agent can use all tools within a defined scope | Scope = directory tree, specific tool set, or resource pattern |
| REQ-03.4 | **Tier 3 — "Autopilot"**: All tools allowed, no approval needed | For trusted, long-running autonomous work |
| REQ-03.5 | Permission level switchable at runtime (CLI command or GUI toggle) | No restart required |
| REQ-03.6 | Permission profiles stored in config files | Named profiles: "safe", "dev-work", "full-auto", custom |
| REQ-03.7 | Per-agent permission overrides | Orchestrator may have higher permissions than workers |
| REQ-03.8 | Audit log of all permission decisions | Who approved what, when, for which agent |

### REQ-04: Multi-Agent Team Architecture

**Goal:** Orchestrator + worker pattern where agents collaborate on complex tasks.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.1 | Orchestrator agent that decomposes tasks and delegates to workers | Single orchestrator per team (can be swapped/configured) |
| REQ-04.2 | Worker agents that execute specific subtasks | Workers can be specialized (coder, researcher, reviewer, etc.) |
| REQ-04.3 | Inter-agent communication via message passing | Structured messages, not free-text piping |
| REQ-04.4 | Agent lifecycle management — spawn, monitor, pause, resume, kill | Harness manages all agent processes |
| REQ-04.5 | Team composition defined in config files | YAML/TOML: which agents, what roles, what models, what permissions |
| REQ-04.6 | Shared context/workspace between team members | Agents can read each other's outputs and shared state |
| REQ-04.7 | Dynamic worker spawning — orchestrator can create new workers as needed | Not limited to pre-defined team size |

### REQ-05: Dual Interface — CLI and GUI

**Goal:** Full functionality available through both CLI and a graphical interface.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-05.1 | CLI for all operations — start, stop, configure, monitor, interact | Scriptable, pipe-friendly |
| REQ-05.2 | GUI for real-time monitoring and interaction | Web-based (localhost) for cross-platform compatibility |
| REQ-05.3 | Live view of all agents: status, current task, recent output | Dashboard-style overview |
| REQ-05.4 | Ability to send messages to any agent from either interface | Chat with orchestrator or individual workers |
| REQ-05.5 | GUI shows agent communication graph / message flow | Visual representation of who's talking to whom |
| REQ-05.6 | CLI and GUI share the same backend — no feature disparity | GUI is a frontend to the same API the CLI uses |

### REQ-06: Autonomous Long-Running Operation ("Anti-Babysitting")

**Goal:** Agents run to completion without unnecessary human check-ins. They stop only when truly done or truly stuck.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-06.1 | Agents must not pause for confirmation unless genuinely blocked | No "shall I continue?" after every step |
| REQ-06.2 | Clear "done" criteria per task — agents self-verify completion | Run tests, check outputs, validate against spec |
| REQ-06.3 | Stuck detection — recognize when no progress is being made | Loop detection, repeated failures, resource exhaustion |
| REQ-06.4 | Graceful degradation on stuck — try alternatives before escalating | Retry with different approach, ask a different agent, then escalate |
| REQ-06.5 | Human escalation only as last resort, with full context | "I tried X, Y, Z. Here's where I'm stuck. Here's what I need from you." |
| REQ-06.6 | Progress persistence — survive crashes, reboots, network drops | Checkpoint state to disk regularly |
| REQ-06.7 | Configurable autonomy timeout | "Run for max 4 hours, then pause and report" |

### REQ-07: Context & Memory Management

**Goal:** Agents maintain useful context across sessions and share knowledge within teams.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-07.1 | Persistent conversation/task context across sessions | Stored on disk, survives restarts |
| REQ-07.2 | Checkpoint and resume for long-running tasks | Explicit checkpoints + auto-checkpoint on interval |
| REQ-07.3 | Shared knowledge base between team agents | Worker B can see what Worker A discovered |
| REQ-07.4 | Context windowing — manage context size vs. model limits | Automatic summarization, sliding window, or retrieval-augmented |
| REQ-07.5 | Task history — browse and search past tasks and their outcomes | Queryable from CLI and GUI |

### REQ-08: Tool System (Plugin Architecture)

**Goal:** Extensible tool system where adding a new tool is dropping a file in a directory.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-08.1 | Plugin-based tool loading — file-per-tool or directory-per-tool | Auto-discovery on startup |
| REQ-08.2 | Standard tool interface: name, description, input schema, execute() | Minimal boilerplate to create a new tool |
| REQ-08.3 | Built-in tools: file read/write, shell exec, web fetch, code search | Ship with a useful default set |
| REQ-08.4 | Tool usage audit log | Tool name, args, result, duration, which agent, approval status |
| REQ-08.5 | Tool timeout and resource limits | Prevent a single tool call from hanging the system |
| REQ-08.6 | Tool result caching (optional, per-tool) | Avoid redundant expensive calls |

---

## P1 — Important (Daily Use)

### REQ-09: Cost & Resource Tracking

**Goal:** Know what your agents are consuming and set limits.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-09.1 | Token usage tracking per agent, per task, per session | Input tokens, output tokens, total |
| REQ-09.2 | Budget limits — max tokens, max time, max tool calls | Per-agent and per-task limits |
| REQ-09.3 | Resource dashboard in GUI, summary in CLI | Real-time and historical |
| REQ-09.4 | Alerts when approaching limits | Configurable thresholds (80%, 90%, 100%) |
| REQ-09.5 | Cost estimation for cloud providers (when used) | Map token counts to approximate $ cost |

### REQ-10: Observability & Debugging

**Goal:** Full visibility into what agents are doing and why.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-10.1 | Full reasoning chain trace (not just final output) | Every LLM call, tool call, decision point |
| REQ-10.2 | Session replay from logs | Re-watch what happened step by step |
| REQ-10.3 | Structured logging with configurable levels | Debug (internals), Info (progress), Warn, Error |
| REQ-10.4 | Error recovery — restart crashed agents from last checkpoint | Automatic or manual |
| REQ-10.5 | Log export in standard formats (JSON, OpenTelemetry) | For integration with external observability tools |

### REQ-11: Task Specification & Acceptance Criteria

**Goal:** Structured way to define what "done" means so agents can self-verify.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-11.1 | Task definition format with description, acceptance criteria, verification steps | YAML/TOML/Markdown |
| REQ-11.2 | Verification step execution — run tests, check files, validate output | Automated pass/fail |
| REQ-11.3 | Task decomposition tracking — see how orchestrator broke down a task | Tree view in GUI |
| REQ-11.4 | Task dependencies — "do B after A completes" | DAG-based task scheduling |
| REQ-11.5 | Task status lifecycle: pending → in-progress → verifying → done/failed/blocked | Clear state machine |

### REQ-12: Security & Sandboxing

**Goal:** Protect the host system from runaway or malicious agent behavior.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-12.1 | Sandboxed execution for shell commands | Container, chroot, or OS-level sandboxing |
| REQ-12.2 | Network access controls per agent | Allow/deny internet, allow only localhost, etc. |
| REQ-12.3 | Secret management — agents can use API keys without seeing raw values | Injected at runtime, masked in logs |
| REQ-12.4 | File system boundaries — agents can only access allowed paths | Enforced by the harness, not just by convention |
| REQ-12.5 | Command allowlist/denylist | Block dangerous commands (rm -rf /, etc.) |

### REQ-13: Configuration as Code

**Goal:** Everything configurable via version-controlled files.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-13.1 | Agent definitions in config files (YAML or TOML) | Name, role, model, system prompt, tools, permissions |
| REQ-13.2 | Team compositions as named configs | "coding-team", "research-team", "solo-debug" |
| REQ-13.3 | Permission profiles as named configs | "safe", "dev-work", "full-auto" |
| REQ-13.4 | Environment-specific overrides | Dev vs. CI vs. production settings |
| REQ-13.5 | Config validation on startup | Fail fast with clear error messages |
| REQ-13.6 | Config hot-reload where possible | Change a config, see it take effect without restart |

### REQ-14: Human-in-the-Loop Escalation Patterns

**Goal:** Smart escalation that doesn't block all work when one thing needs human input.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-14.1 | Asynchronous question queue — agent posts question, continues other work | Non-blocking escalation |
| REQ-14.2 | Priority-based interrupts — blocked on A, move to B | Orchestrator manages work redistribution |
| REQ-14.3 | Notification system — desktop, email, or webhook when agent needs you | Configurable channels |
| REQ-14.4 | Escalation context — full history of what was tried before escalating | Human gets enough context to answer quickly |
| REQ-14.5 | Batch approval — review and approve multiple pending requests at once | Efficient for returning after AFK |

### REQ-15: Testing & Evaluation Framework

**Goal:** Measure and compare agent performance systematically.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-15.1 | A/B testing — same task, different models/configs, compare results | Side-by-side output comparison |
| REQ-15.2 | Benchmark suite — standard tasks for regression testing | Customizable per project |
| REQ-15.3 | Regression detection — alert when config changes degrade performance | Automated comparison against baseline |
| REQ-15.4 | Eval metrics — task completion rate, time, token usage, tool calls | Quantitative and qualitative |
| REQ-15.5 | Eval results stored and browsable | Historical trends |

---

## P2 — Nice-to-Have (Polish & Power)

### REQ-16: Multi-Model Routing

**Goal:** Use the right model for the right job, with automatic fallbacks.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-16.1 | Per-agent model assignment | Orchestrator = strong model, simple workers = fast/cheap model |
| REQ-16.2 | Fallback chains — if primary model is down/slow, use backup | Ollama → cloud provider, or large model → small model |
| REQ-16.3 | Load-based routing — distribute across multiple local model instances | For multi-GPU setups |
| REQ-16.4 | Model capability tagging — match task requirements to model strengths | "needs code generation" → route to code-specialized model |

### REQ-17: Artifact Management

**Goal:** Track, version, and review everything agents produce.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-17.1 | Artifact collection — gather all outputs (code, docs, reports) | Per-task artifact directory |
| REQ-17.2 | Diff view of codebase changes made by agents | Git-style diffs in GUI |
| REQ-17.3 | Accept/reject/edit agent outputs before committing | Review gate |
| REQ-17.4 | Artifact versioning — track iterations of the same output | "Draft 1, Draft 2, Final" |
| REQ-17.5 | Artifact export — package outputs for sharing | Zip, git bundle, etc. |

### REQ-18: Session & Workflow Templates

**Goal:** Capture successful workflows and replay them.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-18.1 | Save a workflow as a reusable template | "Do code review like last time" |
| REQ-18.2 | Parameterized templates — same workflow, different inputs | Template variables |
| REQ-18.3 | Import/export/share templates | File-based, easy to version control |
| REQ-18.4 | Template marketplace / community sharing (future) | Optional, not required for MVP |

### REQ-19: Rate Limiting & Backpressure

**Goal:** Prevent resource exhaustion when running many agents.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-19.1 | Rate limiting on LLM API calls | Per-provider, configurable |
| REQ-19.2 | Tool call queue with concurrency limits | Max N parallel shell commands, etc. |
| REQ-19.3 | Backpressure — pause low-priority agents when system is loaded | Priority-based scheduling |
| REQ-19.4 | Resource monitoring — CPU, memory, GPU utilization | Alert when system is overloaded |

### REQ-20: Offline-First Design

**Goal:** Full functionality with local models, graceful degradation without network.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-20.1 | Core functionality works with zero internet access | Ollama + local tools = fully functional |
| REQ-20.2 | Cloud features degrade gracefully — no crashes if network is down | Clear error messages, automatic fallback to local |
| REQ-20.3 | Local model management — pull, list, update Ollama models from harness | `agent-harness models list`, `agent-harness models pull llama3` |
| REQ-20.4 | Offline documentation — built-in help that doesn't require web access | `agent-harness help <topic>` |

---

## Cross-Cutting Concerns

These apply across all requirements:

| Concern | Requirement |
|---------|-------------|
| **Logging** | All components use structured logging with consistent format |
| **Error handling** | All errors are caught, logged, and surfaced clearly — no silent failures |
| **Testing** | All components have unit tests; integration tests for critical paths |
| **Documentation** | All public APIs, config formats, and tool interfaces are documented |
| **Performance** | Response latency targets: CLI commands < 200ms, GUI updates < 500ms, agent message relay < 100ms |
| **Backwards compatibility** | Config format changes are versioned; old configs produce clear migration instructions |

---

## Technology Decisions (To Be Made)

| Decision | Options to Evaluate | Notes |
|----------|---------------------|-------|
| Primary language | Python, TypeScript, Rust, Go | Python has best LLM ecosystem; Go/Rust for performance |
| GUI framework | Web (React/Svelte), TUI (Textual/Ratatui), Electron | Web = most cross-platform |
| Config format | YAML, TOML, JSON | TOML preferred for readability |
| IPC mechanism | HTTP/REST, gRPC, Unix sockets, message queue | Between harness core and agents |
| Storage | SQLite, flat files, embedded KV store | For context, logs, artifacts |
| Sandboxing | Docker, Bubblewrap, OS-native | Platform-dependent |

---

## Glossary

| Term | Definition |
|------|------------|
| **Harness** | The core runtime that manages agents, tools, permissions, and communication |
| **Agent** | An LLM-powered entity with a role, tools, and permissions |
| **Orchestrator** | A special agent that decomposes tasks and delegates to workers |
| **Worker** | An agent that executes specific subtasks assigned by the orchestrator |
| **Tool** | A capability an agent can invoke (file read, shell exec, web fetch, etc.) |
| **Team** | A configured group of agents working together on a task |
| **Session** | A single run of a task or workflow, from start to completion |
| **Checkpoint** | A saved snapshot of agent/task state for resume after interruption |
| **Profile** | A named configuration (permission profile, team profile, etc.) |
