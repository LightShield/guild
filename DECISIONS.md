# Guild — Implementation Decisions

Decisions made during implementation that weren't covered in REQUIREMENTS.md or ARCHITECTURE.md.

## D-01: Permission prompt_fn injection

**Decision:** The `PermissionChecker` accepts an optional `prompt_fn` callable for the ASK tier instead of hardcoding `input()`.

**Why:** Hardcoded `input()` is untestable and breaks in non-interactive contexts (pytest, CI, background agents). The injected function has signature `(tool_name, agent_id, args) -> bool`. The default implementation uses `input()` for interactive CLI use.

**Impact:** Tests can mock the prompt. Future GUI can inject a different approval mechanism.

## D-02: Tool path resolution

**Decision:** All file-based tools (`file_read`, `file_write`, `search`, `glob`) resolve relative paths against the agent's `working_dir`.

**Why:** Agents operate in the context of a project directory. Without this, relative paths would resolve against the process CWD, which may differ from the project root.

## D-03: Researcher output type changed to `text`

**Decision:** Changed the researcher block's output port type from `findings` to `text`.

**Why:** The `research-and-implement` team connects researcher → planner, and planner expects `text` input. Using `findings` caused a port type mismatch that the validator correctly caught. `text` is the more general type and the researcher's output is fundamentally text.

## D-04: Team execution uses topological sort with cycle breaking

**Decision:** The `TeamRunner` determines block execution order via topological sort. Loop-back edges (evaluator → generator) are removed before sorting to break cycles.

**Why:** Teams can have feedback loops (coder ↔ reviewer). A naive topological sort would fail on cycles. By removing the loop-back edges, we get a valid linear order, and the loop logic handles the iteration separately.

## D-05: Evaluator pass/fail via deterministic checks first, LLM text as last resort

**Decision:** `LoopDef` now supports `verification_commands` (shell commands) and `verification_files` (file existence checks). If defined, these run first and their result overrides any LLM output. Only if no deterministic checks are defined does the system fall back to parsing the evaluator's text output.

**Why (revised):** The original approach parsed LLM free-text for "pass"/"lgtm" keywords. With weak local models, this is unreliable. Deterministic checks (exit codes, file existence) are 100% reliable. Examples: `verification_commands = ["pytest tests/"]` — if tests pass (exit 0), the loop passes. `verification_files = ["output.txt"]` — if the file exists, the loop passes.

**Fallback chain:** deterministic commands → deterministic files → JSON parsing → keyword heuristics.

## D-06: Learning extraction runs with NOTHING permission tier

**Decision:** The learner agent runs with `PermissionTier.NOTHING` (no tools) and `max_turns=1`.

**Why:** The learner only needs to analyze text (session logs) and produce JSON output. It doesn't need file access or shell commands. Running with no tools is safer and cheaper.

## D-07: CLI name collision with GNU Guile

**Decision:** The `guild` CLI entry point collides with GNU Guile's `guild` command on some systems. For now, use `~/.local/bin/guild` or `python3 -m guild.cli.main`.

**Why:** Renaming the CLI would break the branding. This is a PATH ordering issue, not a fundamental conflict. Can be resolved with an alias or by ensuring `~/.local/bin` is earlier in PATH.

**Future:** Consider adding a `gld` alias as a short alternative.

## D-08: Session approvals in ASK tier are per-tool, not per-call

**Decision:** When a user approves a tool in ASK mode, the approval is remembered for that tool name for the rest of the session. They don't need to approve every individual call.

**Why:** Per-call approval is too noisy for real use. An agent might call `file_read` 50 times in a session. The user can still deny individual tools while approving others.

## D-09: Runtime permission switching clears session approvals

**Decision:** When `set_tier()` is called, all session-level tool approvals are cleared.

**Why:** Switching from ASK to SCOPED and back shouldn't carry over approvals from the previous tier. The user's intent when switching tiers is to change the security posture, so stale approvals should be discarded.

## D-10: Stuck detection thresholds configurable via config.toml

**Decision:** Stuck detection thresholds are fields on `GuildConfig` and loadable from `[guild]` section in config.toml: `stuck_max_repeated_errors`, `stuck_max_no_progress_turns`, `stuck_max_repeated_calls`.

**Why (revised):** Original had hardcoded defaults. User feedback: these should be configurable since optimal thresholds depend on the task and model. Defaults remain 3/10/3 but can be overridden per-project.

## D-11: Multi-turn chat works by design, no special session mechanism

**Decision:** `AgentLoop.run()` appends to `self.messages` without clearing between calls. This means calling `run()` multiple times on the same `AgentLoop` instance naturally preserves conversation context.

**Why:** The simplest correct implementation. No session management, no serialization/deserialization between turns. The agent loop is already stateful — we just don't reset it. The `guild chat` command creates one `AgentLoop` and calls `run()` in a loop.

**Trade-off:** If the conversation gets very long, context will grow unbounded. This is where the multi-tier compression (REQ-07.4) will be needed, but that's a separate feature.

## D-12: Audit log is append-only, queryable via CLI

**Decision:** The audit log is a simple append-only SQLite table. The `guild audit` command shows entries newest-first with a configurable `--limit`.

**Why:** Audit logs should never be modified or deleted. Append-only is the simplest correct model. The CLI provides basic querying; more advanced filtering can be added later.

## D-13: Stuck detection always-on, no opt-in flag

**Decision:** `StuckDetector` is always active in `AgentLoop`. The `enable_stuck_detection` parameter was removed.

**Why (revised):** User feedback: there's no real downside to always-on detection. The overhead is negligible (list appends + comparisons). Pre-release, no backwards compatibility concern. Every agent benefits from loop/error detection.

## D-14: ToolResult structured return type replacing raw strings

**Decision:** All tool executors return `ToolResult(success: bool, output: str, error: str | None)` instead of raw strings. The harness uses `success` for stuck detection and audit logging. `str(ToolResult)` produces the text shown to the LLM.

**Why (revised):** Original approach detected errors by checking if the string started with "Error:" — brittle and convention-dependent. `ToolResult` is the standard practice in tool-use systems. The harness gets a definitive success/failure signal without parsing. Custom tools follow the same contract.

**Impact:** Shell commands with non-zero exit codes are now `success=False`. File-not-found is `success=False`. Search with no matches is `success=True` (no matches is not an error). Unknown tools are `success=False`.

## D-15: MicroCompact preserves message count, only truncates content

**Decision:** Context compression never removes messages from the conversation — it only shortens their content. System prompt and recent N messages are fully preserved. Old tool outputs are truncated oldest-first.

**Why:** Removing messages could break tool call/result pairing (the model expects a tool result for every tool call). Truncation preserves the conversation structure while reducing token count. The `[truncated]` marker tells the model that content was shortened.

## D-16: Autonomy timeout is wall-clock, checked per-turn

**Decision:** `timeout_seconds` is checked at the start of each turn (before calling the model). It uses `time.monotonic()` for wall-clock measurement, not token count or turn count.

**Why:** Wall-clock is the most intuitive measure for "run for max 4 hours." Token-based limits are handled separately by budget controls. Turn-based limits already exist via `max_turns`. The check happens before the model call so we don't waste a model call just to discover we're over time.

## D-17: Learning confidence uses asymmetric adjustment

**Decision:** `validate_learning()` increases confidence by +0.1, `invalidate_learning()` decreases by -0.15. Capped at [0.0, 1.0].

**Why:** Invalidation should have more impact than validation — it's easier to confirm something works than to discover it doesn't. A learning that fails once should lose more confidence than it gains from one success. This makes the system conservative: learnings need multiple validations to reach high confidence but can be demoted quickly.

## D-18: Config CLI writes TOML manually

**Decision:** `guild config --set` parses the existing TOML, modifies the value, and writes it back using simple string formatting (not a TOML library writer).

**Why:** Python's `tomllib` is read-only (no write support in stdlib). Adding `tomli-w` as a dependency for one feature is overkill. The manual writer handles the simple flat-section TOML format we use. If config format becomes more complex, we'll add `tomli-w`.

## D-19: GUI is a single HTML file with inline CSS/JS

**Decision:** The entire GUI is one `index.html` file with inline styles and JavaScript. No build step, no npm, no framework.

**Why:** Minimal complexity. The GUI is a monitoring dashboard, not a complex app. A single file means: no build toolchain, no node_modules, instant loading, easy to modify. If the GUI grows significantly, we can migrate to a framework later. The API is the real interface — the GUI is just a view.

## D-20: REST API mirrors CLI functionality exactly

**Decision:** Every API endpoint corresponds to a CLI command. No API-only features. The GUI consumes the same API the CLI could use.

**Why:** REQ-05 requires no feature disparity between CLI and GUI. The API is the shared backend. This also means the API is testable via the same patterns as the CLI.

## D-21: FallbackChain checks health sequentially, not in parallel

**Decision:** `FallbackChain.get_healthy_provider()` checks providers one at a time, stopping at the first healthy one.

**Why:** For local Ollama (the primary use case), there's usually only one provider. Sequential checking is simpler and avoids unnecessary network calls to backup providers. If the primary is healthy (the common case), we never touch the fallbacks.

## D-22: RPG mode is text substitution only, not a separate UI

**Decision:** RPG mode uses `rpg_translate()` to swap terms in the existing UI. It doesn't create a separate RPG-themed interface.

**Why:** Maintaining two UIs would be expensive. Text substitution achieves the fun factor (tasks→quests, agents→heroes) with zero additional UI code. The visual theme (dark, animated) already looks game-like.

## D-23: Rate limiter uses token bucket algorithm

**Decision:** `RateLimiter` implements a sliding window token bucket: tracks timestamps of recent calls, blocks when the window is full.

**Why:** Token bucket is the standard rate limiting algorithm. It's simple, handles bursts well, and doesn't require external state. The window-based approach naturally expires old calls.

## D-24: Templates use simple string replacement, not Jinja2

**Decision:** Template rendering uses `str.replace("{param}", value)` instead of a template engine.

**Why:** Our templates have simple `{parameter}` placeholders. Adding Jinja2 for this is overkill. If templates need conditionals or loops in the future, we'll add Jinja2 then.
