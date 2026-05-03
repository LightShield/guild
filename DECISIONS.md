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
