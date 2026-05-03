# Guild — Requirements Specification

**Version:** 0.1.0
**Date:** 2026-05-03
**Author:** Or Magen

---

## Overview

A locally-focused, cross-platform agent harness (Guild) that enables running LLM-powered agent teams with full autonomy, observability, and control. Designed to work primarily with local models (Ollama) while remaining provider-agnostic, and to support long-running autonomous workflows with robust permission controls.

---

## Priority Tiers

| Tier | Meaning | Target |
|------|---------|--------|
| **P0** | MVP — must have for first usable version | v0.1 |
| **P1** | Important — needed for real daily use | v0.2 |
| **P2** | Nice-to-have — adds polish and power | v0.3+ |

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
| REQ-02.3 | Single update mechanism | `guild update` or equivalent |
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

### REQ-04: Multi-Agent Team Architecture & Composable Blocks

**Goal:** Entry agent (user-facing) that can spawn any agents, including other orchestrators. Flat, composable architecture — not a rigid hierarchy. Teams are built from reusable building blocks.

#### 4A: Core Agent Architecture

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.1 | **Entry agent is always the orchestrator** — every project starts with this agent as the user's interface | User always communicates with this base agent; it delegates, spawns workers, and manages the team |
| REQ-04.2 | The entry agent is present even in preset team compositions | "Start new project with dev-loop team" → entry agent is created, wires up the team, and becomes the point of contact |
| REQ-04.3 | Any agent can spawn other agents, including other orchestrators | No rigid hierarchy — an agent spawning a sub-orchestrator for a complex subtask is valid |
| REQ-04.4 | Agent spawning is just another tool call — keep architecture flat | Per Claude Code insight: no separate multi-agent runtime, sub-agents are tool invocations |
| REQ-04.5 | Worker agents that execute specific subtasks | Workers can be specialized (coder, researcher, reviewer, etc.) |
| REQ-04.6 | **MCP (Model Context Protocol) for agent-to-tool communication** | Industry standard — agents connect to tools/data via MCP servers |
| REQ-04.7 | **Simple internal message bus for agent-to-agent communication** | `send(agent_id, port, data)` / `receive()` — direct, no network overhead, easy to debug |
| REQ-04.7a | **A2A as optional external gateway (P2)** | Only for cross-Guild communication with external agents; internal bus wraps to A2A-compatible interface later |
| REQ-04.8 | **Skills support** — agents can have pluggable skill definitions | Skill files that define capabilities, similar to Claude Code's SKILL.md pattern |
| REQ-04.9 | Agent lifecycle management — spawn, monitor, pause, resume, kill | Guild manages all agent processes |
| REQ-04.10 | Shared context/workspace between team members | Agents can read each other's outputs and shared state; cache sharing for token efficiency |
| REQ-04.11 | Dynamic worker spawning — entry agent or any orchestrator can create new workers as needed | Not limited to pre-defined team size |
| REQ-04.12 | Isolated execution environments for parallel workers | Separate worktrees/directories to prevent conflicts during parallel edits |

#### 4B: Composable Agent Blocks

Agents and agent patterns are **building blocks** that can be composed, connected, saved, and reused. Think of it like a visual circuit board — individual components snap together into larger patterns, and those patterns become reusable components themselves.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.20 | **Atomic blocks** — single-agent building blocks with defined inputs/outputs/role | e.g., "coder", "reviewer", "researcher", "evaluator", "planner" |
| REQ-04.21 | **Composite blocks** — groups of connected blocks saved as a single reusable unit | e.g., "coder + evaluator" = a "verified-coder" block; "planner + coder + reviewer + tester" = a "dev-loop" block |
| REQ-04.22 | **Block connectors** — defined input/output ports that determine how blocks wire together | Output of "coder" feeds into input of "reviewer"; reviewer output feeds back to coder or forward to "tester" |
| REQ-04.23 | **Block library** — a local catalog of available atomic and composite blocks | Ships with built-in blocks; user creates and saves custom ones |
| REQ-04.24 | **Visual team composer in GUI** — drag-and-drop blocks, connect them, save as team config | Like a node-based editor (think Unreal Blueprints / Node-RED style) |
| REQ-04.25 | **CLI team composer** — equivalent text-based composition via config files | YAML/TOML that describes the same graph the GUI shows |
| REQ-04.26 | **Nesting** — composite blocks can contain other composite blocks | A "dev-loop" block can be dropped into a larger "full-project" team |
| REQ-04.27 | **Block versioning** — blocks are versioned; each reference pins a version or opts into `latest` | Default: pinned to current version at composition time. Set `version: "latest"` for auto-update |
| REQ-04.28 | **Loop/cycle support in block graphs** — blocks can form feedback loops | "coder → reviewer → coder" is a valid cycle; exit condition defined by the evaluating block |

#### 4B-i: Block Port Type System

Blocks declare typed input/output ports. Guild validates port compatibility **at composition time** (when you wire blocks together in the GUI or config), not at runtime.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.30 | Every port has a **type tag** and optional **JSON schema** | Type tags: `plan`, `code-changes`, `review`, `test-results`, `findings`, `document`, `learnings`, `text`, `files`, `any` |
| REQ-04.31 | Port compatibility checked at composition time | GUI: incompatible connection shows red/blocked. CLI: config validation rejects it with clear error |
| REQ-04.32 | `any` type is the escape hatch — accepts/produces anything | For flexible blocks that work with arbitrary data |
| REQ-04.33 | Composite blocks expose unconnected inner ports as their own ports | A composite's external interface is derived from its internal wiring |
| REQ-04.34 | New type tags can be registered by users | Extensible — not limited to built-in types |
| REQ-04.35 | Port data is always serializable (JSON) | Enables persistence, logging, and replay |

#### 4B-ii: Evaluator Contract & Exit Conditions

Each evaluator block defines its own criteria and what "pass" means. The block graph only needs to know: did it pass or fail?

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.40 | **Standard evaluator output**: `{pass: bool, score: 0-100, feedback: string, details: {...}}` | All evaluator blocks produce this shape; internals vary |
| REQ-04.41 | **Each evaluator defines its own rubric/criteria** | Code reviewer checks correctness + style; test evaluator checks coverage + correctness; research evaluator checks completeness + accuracy |
| REQ-04.42 | **Loop exit checks `pass`** — the feedback loop continues until the evaluator says `pass: true` | Score and feedback flow back to the generator block for iteration |
| REQ-04.43 | **Max iteration safety limit** per loop — configurable, default 5 | Prevents infinite loops even if evaluator never passes |
| REQ-04.44 | **Evaluator criteria are part of the block config** — editable per-instance | Same evaluator block type, different criteria for different contexts |

#### 4B-iii: Error Propagation in Block Graphs

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.50 | **Block fails → retry N times** (configurable per-block, default 1) | Transient failures handled locally |
| REQ-04.51 | **Still failing → escalate to caller** (the block/agent that spawned it) | Error includes: what failed, what was tried, full context chain |
| REQ-04.52 | **Caller decides**: retry with different approach, skip and continue, substitute another block, or escalate further | Caller has autonomy over error handling strategy |
| REQ-04.53 | **Error reaches entry agent with no resolution → escalate to human** | Last resort; human gets full error chain with context |
| REQ-04.54 | **Partial failure in parallel branches** — other branches continue; failed branch is reported | Don't kill the whole team because one worker failed |

#### 4C: Built-in Atomic Blocks (Ship with Guild)

These are the starter set of single-agent blocks. Each has a defined role, default system prompt, default tools, and typed input/output ports.

| Block | Role | Input Ports (type) | Output Ports (type) |
|-------|------|--------------------|---------------------|
| **planner** | Decomposes a high-level task into a structured plan | `task: text` | `plan: plan` |
| **coder** | Writes code to fulfill a specification | `spec: plan`, `context: files` | `changes: code-changes` |
| **reviewer** | Reviews code for correctness, style, spec compliance | `changes: code-changes`, `spec: plan` | `result: review` |
| **tester** | Writes and runs tests against code | `changes: code-changes`, `spec: plan` | `result: test-results` |
| **evaluator** | Judges quality of any output against criteria | `artifact: any`, `criteria: text` | `result: review` (standard evaluator contract) |
| **researcher** | Investigates unknowns — reads docs, searches code | `question: text` | `report: findings` |
| **writer** | Produces documentation, reports, specs | `topic: text`, `context: any` | `doc: document` |
| **learner** | Extracts lessons from completed work (see REQ-09) | `logs: any`, `outcomes: any` | `insights: learnings` |

#### 4D: Built-in Composite Blocks (Reusable Patterns)

These ship as pre-built compositions that users can use directly or customize.

| Composite Block | Composition | Loop? | Description |
|-----------------|-------------|-------|-------------|
| **verified-coder** | coder → evaluator | Yes (coder iterates until evaluator passes) | Code with built-in quality gate |
| **dev-loop** | planner → coder → tester → reviewer | Yes (reviewer can send back to coder) | Standard development cycle |
| **research-and-implement** | researcher → planner → verified-coder | No | Investigate first, then build |
| **dev-loop-with-learning** | dev-loop → learner | No | Dev cycle that captures lessons for next time |

### REQ-05: Dual Interface — CLI-First, GUI as Wrapper

**Goal:** CLI is the complete, authoritative interface. GUI is a web wrapper on top of the CLI/API — no feature disparity, no GUI-only functionality.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-05.1 | **CLI is the primary interface** — every operation is a CLI command | Scriptable, pipe-friendly, automatable |
| REQ-05.2 | All agent interaction, team composition, monitoring, and config happens via CLI | Nothing requires the GUI |
| REQ-05.3 | CLI exposes a local REST API that the GUI consumes | GUI is purely a frontend to this API |
| REQ-05.4 | **GUI (P1)** — web-based (localhost) real-time monitoring and interaction | Dashboard: agent status, current tasks, recent output |
| REQ-05.5 | **Visual team composer (P2)** — drag-and-drop block editor in GUI | Node-based editor; equivalent to editing YAML team configs by hand |
| REQ-05.6 | Ability to send messages to any agent from CLI or GUI | `guild chat <agent>` in CLI; chat panel in GUI |
| REQ-05.7 | GUI shows agent communication graph / message flow | Visual representation of who's talking to whom |

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
| REQ-06.8 | **Simple core loop** — while(true) { call model → execute tool → append result } | Per Claude Code: don't overengineer the control flow; complexity lives in the harness |
| REQ-06.9 | **Quality gates via composable blocks, not hardcoded patterns** | Generator+evaluator is a team composition pattern (see REQ-04B), not a built-in autonomy feature |

### REQ-07: Context & Memory Management

**Goal:** Agents maintain useful context across sessions and share knowledge within teams. Memory is indexed hints, not trusted truth.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-07.1 | Persistent conversation/task context across sessions | Stored on disk, survives restarts |
| REQ-07.2 | Checkpoint and resume for long-running tasks | Explicit checkpoints + auto-checkpoint on interval |
| REQ-07.3 | Shared knowledge base between team agents | Worker B can see what Worker A discovered; cache sharing for token efficiency |
| REQ-07.4 | **Multi-tier context compression** — local trim → model-based summarization → full compact with re-injection | Per Claude Code: MicroCompact (zero API calls) → AutoCompact (near ceiling) → Full Compact |
| REQ-07.5 | **Skeptical memory** — agent verifies memories against actual state before acting | Memory entries are hints, not trusted facts (per Claude Code pattern) |
| REQ-07.6 | Lightweight memory index always loaded, detailed notes fetched on demand | Index <200 lines, topic files loaded as needed |
| REQ-07.7 | Memory consolidation during idle time | Merge observations, remove contradictions, confirm tentative notes |
| REQ-07.8 | **Context resets with structured handoff** for very long tasks | Clear context + handoff artifact can outperform in-place compaction |
| REQ-07.9 | Task history — browse and search past tasks and their outcomes | Queryable from CLI and GUI |
| REQ-07.10 | **Static/dynamic prompt separation** for cache efficiency | Static instructions (cacheable) separated from session-specific dynamic content |

### REQ-08: Tool System (Plugin Architecture)

**Goal:** MCP-native tool system. Built-in tools are dedicated and typed (not a generic shell). Adding a new tool is dropping a file in a directory.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-08.1 | **MCP-native tool interface** — tools are MCP servers or expose MCP-compatible schemas | Industry standard; enables reuse of existing MCP ecosystem |
| REQ-08.2 | Plugin-based tool loading — file-per-tool or directory-per-tool | Auto-discovery on startup |
| REQ-08.3 | Standard tool contract: name, description, input schema (Zod/JSON Schema), execute(), behavioral properties | Properties like isConcurrencySafe, isReadOnly enable optimization (per Claude Code pattern) |
| REQ-08.4 | **Dedicated typed tools over generic shell** — replace frequent shell commands with purpose-built tools | File read/write, code search, grep, glob — each with its own permissions and validation |
| REQ-08.5 | Built-in tools: file read/write, shell exec (with safety checks), web fetch, code search, grep, glob | Ship with a useful default set; shell tool has embedded safety rules |
| REQ-08.6 | Tool usage audit log | Tool name, args, result, duration, which agent, approval status |
| REQ-08.7 | Tool timeout and resource limits | Prevent a single tool call from hanging the system |
| REQ-08.8 | Tool result caching (optional, per-tool) | Avoid redundant expensive calls |
| REQ-08.9 | Safety rules embedded in tool descriptions | Per Claude Code insight: model sees constraints at invocation time |

### REQ-09: Long-Term Learning Loop

**Goal:** Guild gets smarter over time. Every completed task is an opportunity to extract knowledge that improves future runs.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-09.1 | **Post-task learning extraction** — after each task completes, a learner agent reviews what happened | Extracts: what worked, what failed, what was slow, what patterns emerged |
| REQ-09.2 | **Knowledge categories**: patterns (reusable approaches), anti-patterns (mistakes to avoid), tool tips (effective tool usage), domain knowledge (project-specific facts) | Structured, not free-text dump |
| REQ-09.3 | **Confidence scoring** — learnings start as tentative, get promoted to confirmed after repeated validation | Prevents one-off flukes from becoming "knowledge" |
| REQ-09.4 | **Learning injection** — confirmed learnings are automatically available to agents in future sessions | Injected into context as hints (per skeptical memory pattern) |
| REQ-09.5 | **Learning review** — human can browse, edit, approve, or reject extracted learnings | CLI and GUI; human stays in control of the knowledge base |
| REQ-09.6 | **Cross-task learning** — patterns from task A inform task B | "Last time we did X, it worked well" / "Last time we tried Y, it failed because Z" |
| REQ-09.7 | **Block-level learning** — learnings can be scoped to specific blocks or block compositions | "When using the dev-loop block, always run linting before tests" |
| REQ-09.8 | **Learning decay** — old learnings that haven't been validated recently lose confidence | Prevents stale knowledge from accumulating |
| REQ-09.9 | **Prompt/config refinement suggestions** — learner can suggest improvements to agent prompts or block configs based on observed patterns | "The reviewer agent misses type errors — suggest adding 'pay attention to type safety' to its prompt" |

---

## P1 — Important (Daily Use)

### REQ-10: Cost & Resource Tracking

**Goal:** Know what your agents are consuming and set limits.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-10.1 | Token usage tracking per agent, per task, per session | Input tokens, output tokens, total |
| REQ-10.2 | Budget limits — max tokens, max time, max tool calls | Per-agent and per-task limits |
| REQ-10.3 | Resource dashboard in GUI, summary in CLI | Real-time and historical |
| REQ-10.4 | Alerts when approaching limits | Configurable thresholds (80%, 90%, 100%) |
| REQ-10.5 | Cost estimation for cloud providers (when used) | Map token counts to approximate $ cost |

### REQ-11: Observability & Debugging

**Goal:** Full visibility into what agents are doing and why.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-11.1 | Full reasoning chain trace (not just final output) | Every LLM call, tool call, decision point |
| REQ-11.2 | Session replay from logs | Re-watch what happened step by step |
| REQ-11.3 | Structured logging with configurable levels | Debug (internals), Info (progress), Warn, Error |
| REQ-11.4 | Error recovery — restart crashed agents from last checkpoint | Automatic or manual |
| REQ-11.5 | Log export in standard formats (JSON, OpenTelemetry) | For integration with external observability tools |

### REQ-12: Task Specification & Acceptance Criteria

**Goal:** Structured way to define what "done" means so agents can self-verify.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-12.1 | Task definition format with description, acceptance criteria, verification steps | YAML/TOML/Markdown |
| REQ-12.2 | Verification step execution — run tests, check files, validate output | Automated pass/fail |
| REQ-12.3 | Task decomposition tracking — see how orchestrator broke down a task | Tree view in GUI |
| REQ-12.4 | Task dependencies — "do B after A completes" | DAG-based task scheduling |
| REQ-12.5 | Task status lifecycle: pending → in-progress → verifying → done/failed/blocked | Clear state machine |

### REQ-13: Security & Sandboxing

**Goal:** Protect the host system from runaway or malicious agent behavior.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-13.1 | Sandboxed execution for shell commands | Container, chroot, or OS-level sandboxing |
| REQ-13.2 | Network access controls per agent | Allow/deny internet, allow only localhost, etc. |
| REQ-13.3 | Secret management — agents can use API keys without seeing raw values | Injected at runtime, masked in logs |
| REQ-13.4 | File system boundaries — agents can only access allowed paths | Enforced by Guild, not just by convention |
| REQ-13.5 | Command allowlist/denylist | Block dangerous commands (rm -rf /, etc.) |

### REQ-14: Configuration as Code

**Goal:** Everything configurable via version-controlled files.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-14.1 | Agent definitions in config files (YAML or TOML) | Name, role, model, system prompt, tools, permissions |
| REQ-14.2 | Team compositions as named configs | "coding-team", "research-team", "solo-debug" |
| REQ-14.3 | Permission profiles as named configs | "safe", "dev-work", "full-auto" |
| REQ-14.4 | Environment-specific overrides | Dev vs. CI vs. production settings |
| REQ-14.5 | Config validation on startup | Fail fast with clear error messages |
| REQ-14.6 | Config hot-reload where possible | Change a config, see it take effect without restart |

### REQ-15: Human-in-the-Loop Escalation Patterns

**Goal:** Smart escalation that doesn't block all work when one thing needs human input.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-15.1 | Asynchronous question queue — agent posts question, continues other work | Non-blocking escalation |
| REQ-15.2 | Priority-based interrupts — blocked on A, move to B | Orchestrator manages work redistribution |
| REQ-15.3 | Notification system — desktop, email, or webhook when agent needs you | Configurable channels |
| REQ-15.4 | Escalation context — full history of what was tried before escalating | Human gets enough context to answer quickly |
| REQ-15.5 | Batch approval — review and approve multiple pending requests at once | Efficient for returning after AFK |

### REQ-16: Testing & Evaluation Framework

**Goal:** Measure and compare agent performance systematically.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-16.1 | A/B testing — same task, different models/configs, compare results | Side-by-side output comparison |
| REQ-16.2 | Benchmark suite — standard tasks for regression testing | Customizable per project |
| REQ-16.3 | Regression detection — alert when config changes degrade performance | Automated comparison against baseline |
| REQ-16.4 | Eval metrics — task completion rate, time, token usage, tool calls | Quantitative and qualitative |
| REQ-16.5 | Eval results stored and browsable | Historical trends |

---

## P2 — Nice-to-Have (Polish & Power)

### REQ-17: Multi-Model Routing

**Goal:** Use the right model for the right job, with automatic fallbacks.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-17.1 | Per-agent model assignment | Orchestrator = strong model, simple workers = fast/cheap model |
| REQ-17.2 | Fallback chains — if primary model is down/slow, use backup | Ollama → cloud provider, or large model → small model |
| REQ-17.3 | **Use cheap models for cheap decisions** | Permission checks, safety screening, compression — smallest model that works (per Claude Code pattern) |
| REQ-17.4 | Model capability tagging — match task requirements to model strengths | "needs code generation" → route to code-specialized model |

### REQ-18: Artifact Management

**Goal:** Track, version, and review everything agents produce.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-18.1 | Artifact collection — gather all outputs (code, docs, reports) | Per-task artifact directory |
| REQ-18.2 | Diff view of codebase changes made by agents | Git-style diffs in GUI |
| REQ-18.3 | Accept/reject/edit agent outputs before committing | Review gate |
| REQ-18.4 | Artifact versioning — track iterations of the same output | "Draft 1, Draft 2, Final" |
| REQ-18.5 | Artifact export — package outputs for sharing | Zip, git bundle, etc. |

### REQ-19: Session & Workflow Templates

**Goal:** Capture successful workflows and replay them.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-19.1 | Save a workflow as a reusable template | "Do code review like last time" |
| REQ-19.2 | Parameterized templates — same workflow, different inputs | Template variables |
| REQ-19.3 | Import/export/share templates | File-based, easy to version control |

### REQ-20: Rate Limiting & Backpressure

**Goal:** Prevent resource exhaustion when running many agents.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-20.1 | Rate limiting on LLM API calls | Per-provider, configurable |
| REQ-20.2 | Tool call queue with concurrency limits | Max N parallel shell commands, etc. |
| REQ-20.3 | Backpressure — pause low-priority agents when system is loaded | Priority-based scheduling |
| REQ-20.4 | Resource monitoring — CPU, memory, GPU utilization | Alert when system is overloaded |

### REQ-21: Offline-First Design

**Goal:** Full functionality with local models, graceful degradation without network.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-21.1 | Core functionality works with zero internet access | Ollama + local tools = fully functional |
| REQ-21.2 | Cloud features degrade gracefully — no crashes if network is down | Clear error messages, automatic fallback to local |
| REQ-21.3 | Local model management — pull, list, update Ollama models from Guild | `guild models list`, `guild models pull llama3` |
| REQ-21.4 | Offline documentation — built-in help that doesn't require web access | `guild help <topic>` |

### REQ-22: RPG Fun Mode (UI Theme)

**Goal:** Optional RPG-themed UI skin that makes working with Guild more fun. All functionality stays identical — this is purely a presentation layer toggle.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-22.1 | **UI mode toggle**: "serious" (default) and "RPG" mode | `guild config set ui.mode rpg` or GUI toggle |
| REQ-22.2 | RPG mode renames concepts in the UI only (not in configs/APIs) | Tasks → Quests, Teams → Parties, Blocks → Classes, Entry agent → Guild Master, etc. |
| REQ-22.3 | RPG-style progress indicators | XP bars instead of progress %, "Level Up!" on learning milestones |
| REQ-22.4 | Quest log view for task history | RPG-style quest tracker with status icons |
| REQ-22.5 | Agent "character sheets" showing stats | Model, tools, permissions, tasks completed, learnings contributed |
| REQ-22.6 | Fun notifications in RPG mode | "A new quest has arrived!", "The Coder has leveled up!", "Party wiped — requesting aid from Guild Master" |

---

## Cross-Cutting Concerns

These apply across all requirements:

| Concern | Requirement |
|---------|-------------|
| **Logging** | All components use structured logging with consistent format |
| **Error handling** | All errors are caught, logged, and surfaced clearly — no silent failures |
| **Testing** | All components have unit tests; integration tests with mocked LLM; session recording/replay for regression (see ARCHITECTURE.md AD-06) |
| **Documentation** | All public APIs, config formats, and tool interfaces are documented |
| **Performance** | Response latency targets: CLI commands < 200ms, GUI updates < 500ms, agent message relay < 100ms |
| **Backwards compatibility** | Config format changes are versioned; old configs produce clear migration instructions |

### Unified Storage Architecture

**Single source of truth: SQLite database** with files on disk for large artifacts.

| Data | Storage | Notes |
|------|---------|-------|
| Agent state & context | SQLite | Conversation history, current state, checkpoints |
| Memory & learnings | SQLite | Index, confidence scores, categories, decay timestamps |
| Audit logs | SQLite | Tool calls, permission decisions, agent actions |
| Task history | SQLite | Task definitions, status, decomposition trees, outcomes |
| Block definitions | SQLite + files | Metadata in DB, config files on disk (version-controlled) |
| Team compositions | SQLite + files | Metadata in DB, config files on disk |
| Artifacts (code, docs) | Files on disk, tracked in SQLite | DB stores path, hash, metadata; files stay as files |
| Session traces | SQLite | Full reasoning chains for replay |
| Config | Files on disk | TOML/YAML, read on startup, hot-reloaded |

Design principles:
- SQLite file = single file backup, easy to migrate, queryable
- Large artifacts (code, docs) stay as files — DB tracks references
- All writes go through a storage abstraction layer (not direct SQL) for future flexibility
- WAL mode for concurrent reads during agent execution

---

## Technology Decisions (To Be Made)

| Decision | Options to Evaluate | Notes |
|----------|---------------------|-------|
| Primary language | Python, TypeScript, Rust, Go | Python has best LLM ecosystem; Go/Rust for performance |
| GUI framework | Web (React/Svelte), TUI (Textual/Ratatui), Electron | Web = most cross-platform |
| Config format | YAML, TOML, JSON | TOML preferred for readability |
| IPC mechanism | HTTP/REST, gRPC, Unix sockets, message queue | Between Guild core and agents |
| Storage | SQLite, flat files, embedded KV store | For context, logs, artifacts |
| Sandboxing | Docker, Bubblewrap, OS-native | Platform-dependent |

---

## Glossary

| Term | Definition |
|------|------------|
| **Guild** | The core runtime that manages agents, tools, permissions, and communication |
| **Agent** | An LLM-powered entity with a role, tools, and permissions |
| **Entry Agent** | The user-facing agent — the first point of contact; can delegate to any other agent |
| **Orchestrator** | An agent role (not a fixed system component) that decomposes tasks and delegates to workers |
| **Worker** | An agent that executes specific subtasks assigned by another agent |
| **Block (Atomic)** | A single-agent building block with defined inputs, outputs, and role |
| **Block (Composite)** | A group of connected atomic/composite blocks saved as a reusable unit |
| **Block Library** | The catalog of available blocks (built-in + user-created) |
| **Connector** | The input/output port definition that determines how blocks wire together |
| **Tool** | A capability an agent can invoke (file read, shell exec, web fetch, etc.) |
| **MCP** | Model Context Protocol — industry standard for agent-to-tool communication |
| **A2A** | Agent-to-Agent Protocol — optional (P2) for cross-Guild external agent communication |
| **Message Bus** | Internal agent-to-agent communication mechanism — simple send/receive, no network overhead |
| **Skill** | A pluggable capability definition that gives an agent domain-specific knowledge |
| **Team** | A configured graph of connected blocks working together on a task |
| **Session** | A single run of a task or workflow, from start to completion |
| **Checkpoint** | A saved snapshot of agent/task state for resume after interruption |
| **Profile** | A named configuration (permission profile, team profile, etc.) |
| **Learning** | An extracted insight from completed work, stored with confidence score |
| **Learner** | An agent block that extracts knowledge from completed tasks for future use |
