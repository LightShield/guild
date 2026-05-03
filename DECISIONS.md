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

## D-05: Evaluator pass/fail detection uses JSON + heuristic fallback

**Decision:** `TeamRunner._check_pass()` first tries to parse JSON `{"pass": true/false}` or `{"score": N}` (threshold 70), then falls back to keyword heuristics ("pass", "approved", "lgtm").

**Why:** We can't guarantee the evaluator model will output perfect JSON every time, especially with local models. The heuristic fallback makes the system more robust. The JSON path is preferred and checked first.

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

## D-10: Stuck detection uses three independent strategies

**Decision:** `StuckDetector` checks three conditions independently:
1. Repeated identical errors (same error message N times)
2. No-progress turns (N consecutive turns with `success=False`)
3. Tool call loops (same tool+args called N times)

Any one triggering = stuck.

**Why:** Different failure modes need different detection. An agent might not produce errors but still loop on the same file read. Or it might produce different errors each time but never make progress. Three strategies cover the common cases without being overly complex.

**Thresholds:** Configurable per-detector. Defaults: 3 repeated errors, 10 no-progress turns, 3 repeated calls.

## D-11: Multi-turn chat works by design, no special session mechanism

**Decision:** `AgentLoop.run()` appends to `self.messages` without clearing between calls. This means calling `run()` multiple times on the same `AgentLoop` instance naturally preserves conversation context.

**Why:** The simplest correct implementation. No session management, no serialization/deserialization between turns. The agent loop is already stateful — we just don't reset it. The `guild chat` command creates one `AgentLoop` and calls `run()` in a loop.

**Trade-off:** If the conversation gets very long, context will grow unbounded. This is where the multi-tier compression (REQ-07.4) will be needed, but that's a separate feature.

## D-12: Audit log is append-only, queryable via CLI

**Decision:** The audit log is a simple append-only SQLite table. The `guild audit` command shows entries newest-first with a configurable `--limit`.

**Why:** Audit logs should never be modified or deleted. Append-only is the simplest correct model. The CLI provides basic querying; more advanced filtering can be added later.

## D-13: StuckDetector wired into AgentLoop as opt-in

**Decision:** `StuckDetector` is integrated into `AgentLoop` via `enable_stuck_detection=True` parameter. Disabled by default.

**Why:** Opt-in preserves backwards compatibility. Simple tasks (single-turn Q&A) don't need stuck detection. Long-running autonomous tasks should enable it. The `guild task` CLI command will enable it by default for autopilot mode.

**Behavior when stuck:** Agent appends an explanation message ("I appear to be stuck: <reason>"), sets `self.stuck_reason`, and breaks the loop. The caller (CLI or team runner) can then decide what to do — escalate, retry, or report.

## D-14: Tool errors detected by "Error:" prefix

**Decision:** The stuck detector considers a tool result an error if it starts with "Error:". This is a convention enforced by all built-in tool executors.

**Why:** Simple, deterministic, no LLM needed. All built-in tools already follow this convention. Custom tools should too. A more sophisticated approach (LLM-based error classification) would be overkill for stuck detection.
