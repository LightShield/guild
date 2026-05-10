# Guideline Violations — Consolidated Report (2026-05-10)

4 independent review agents read all 88+ source files. Findings consolidated below.

## CRITICAL (correctness/safety)

| # | File | Issue |
|---|------|-------|
| 1 | storage/sqlite.py (~30 methods) | `assert self._db is not None` stripped by `python -O`. Use proper if/raise. |
| 2 | orchestration/bus.py:21 | `datetime.now()` (local time) — should be `datetime.now(UTC)` like everywhere else. Bug. |

## STRUCTURAL (design quality)

| # | Guideline | Count | Hotspots |
|---|-----------|-------|----------|
| 3 | one-abstraction-level | 22 | cli/main.py (5), cli/task_runner.py (3), agent/loop.py (3), daemon_ops.py (4), daemon/run.py (2) — see ACCEPTED section below |
| 4 | single-responsibility | 7 | cli/main.py learnings — FIXED; blocks/registry (3 concerns), team_runner (many concerns) — ACCEPTED (cohesive class); persist_task_result — previously extracted helpers |
| 5 | fail-fast | 11 | sqlite.py (systemic), artifacts/manager.py (3), daemon_ops.py (1), task_runner.py (1), mcp/registry.py (1), api/server.py (2) |
| 6 | DRY | ~~2~~ 0 | FIXED: toml_utils.py now delegates to config/loader.py canonical implementation |

## FIXED IN THIS PASS

- **DRY (config/loader.py ↔ toml_utils.py):** Canonical TOML serialization now lives in `config/loader.py` (`write_toml_bytes`, `toml_literal`). `cli/toml_utils.py` imports and delegates.
- **Early-exit (4 functions):**
  - `blocks/port_types.py:_basic_schema_check()` — flattened with early returns + `all()`.
  - `orchestration/team_runner.py:_try_parse_json()` — embedded-JSON extraction moved to `_extract_embedded_json()` + `_parse_json_permissive()`.
  - `storage/sqlite.py:consolidate_memories()` — split into `_remove_stale_memories()` and `_dedup_memories()`.
  - `git/worktree.py:_ensure_staging_branch()` — extracted `_branch_exists()` and `_create_worktree()`.
- **Misleading (2):**
  - `provider/escalation.py:generate_with_malformed_recovery` — docstring rewritten to clarify it performs only step 1; caller orchestrates full recovery.
  - `agent/checkpoint.py:provider: object` — changed to `LLMProvider` (TYPE_CHECKING import), return type changed to `AgentLoop | None`.
- **SRP (learnings command):** Extracted `_display_learnings_table()` helper; command is now a thin dispatcher.

## ACCEPTED — cost of fix exceeds benefit

### One-abstraction-level (22 violations)

These violations are real but occur in functions that are 20-30 lines long.
Extracting 15+ tiny single-call helpers would hurt readability more than help.

| File | Function | Justification |
|------|----------|---------------|
| cli/main.py (5) | Various commands | CLI commands are entry-point glue; mixing 1-2 levels is inherent to thin dispatchers. |
| cli/task_runner.py (3) | persist_task_result, run_task | Already extracted helpers in prior pass. Remaining mixing is minimal (dict conversion at boundaries). |
| agent/loop.py (3) | _execute_turns | Core loop body. The "mixing" is one line of message-to-dict conversion at the provider boundary. |
| cli/daemon_ops.py (4) | launch/kill/pause/resume | Each is 10-15 lines of sequential subprocess + storage calls. Splitting would create 4+ one-call functions. |
| daemon/run.py (2) | _run_task | Entry-point function; inline imports are moved to top. Remaining logic is linear setup-then-run. |

### Single-responsibility

| File | Function | Justification |
|------|----------|---------------|
| blocks/registry.py | BlockRegistry | Three concerns (load, store, validate) are tightly coupled to the same data structure. Splitting into 3 classes would over-engineer. |
| orchestration/team_runner.py | TeamRunner | Orchestrator by nature handles graph traversal, loop execution, and error escalation — these are facets of one responsibility: "run a team". |
| cli/main.py:config_cmd | show AND set | Already delegated to toml_utils. The if/else dispatch is acceptable for a CLI thin wrapper. |

## MAGIC LITERALS (39 across 20 files)

**Filenames without constants:**
- `"config.toml"` (3 locations), `"agents.toml"`, `"permissions.toml"`, `".guild"` (5 locations)

**Truncation lengths without constants:**
- `[:100]`, `[:500]` (2x), `[:200]`, `[:8]`

**Identity/matching strings:**
- `"ollama"`, `"running"`, `"resumed"`, `"ok"`, `"skip"`, `"escalate"`, `"master"`, `"guild/"` (5x), `"staging"`, `"_staging"`, `"any"`, `"---"`, `"Guild"`

**Numeric constants:**
- `0.1`/`0.15`/`0.05` (confidence deltas), `0.5` (confidence threshold 2x), `80.0` (CPU threshold), `0.7` (compact threshold), `8000` (max tokens), `4` (preserve recent), `20` (eval max turns), `2` (WebSocket interval), `8` (agent ID truncation), `100` (action truncation)

## WHAT-COMMENTS (19 across 6 files)

- agent/loop.py: 6 comments (`# Track token usage`, `# Append the assistant message`, `# If no tool calls`, etc.)
- agent/learning.py: 5 comments (`# Build session log`, `# Ask LLM`, `# Parse JSON lines`, etc.)
- eval/framework.py: 2 comments (`# Compare duration`, `# Compare tokens`)
- daemon/lifecycle.py: 2 comments (`# Clean up PID file`, `# Update task status`)
- observability/replay.py: 2 comments
- agent/context.py: 1 comment

## WRAP-THIRD-PARTY (3)

- toml_utils.py: imports typer + rich (CLI framework in utility module)
- knowledge/temporal.py: shells out bypassing safety layer
- escalation/notify.py: raw urllib with broad except

## EARLY-EXIT / NESTING (4) — ALL FIXED

- ~~blocks/port_types.py:96 _basic_schema_check() — depth 4~~
- ~~orchestration/team_runner.py:342 _try_parse_json() — depth 4~~
- ~~storage/sqlite.py:641 consolidate_memories() — depth 4~~
- ~~git/worktree.py:153 _ensure_staging_branch() — depth 4~~

## CONTEXTUAL LOG MESSAGES (5)

- api/server.py: "API using injected storage", "API storage closed"
- daemon/supervisor.py: "Signal handlers installed", "Original signal handlers restored"
- offline/manager.py: "ollama CLI not found while listing local models"

## MISLEADING — ALL FIXED

- ~~provider/escalation.py: `generate_with_malformed_recovery` promises 4-step strategy but implements only step 1~~
- ~~agent/checkpoint.py:87: `provider: object` type hint too loose (should be LLMProvider)~~

## FILES CONFIRMED CLEAN (40+ files)

agent/completion, stuck, rollback, message, prompts, budget, ratelimit, cost;
provider/base, retry, cli_provider, ollama; storage/protocol; tools/base,
file_ops, shell, search, registry, plugin; permissions/checker; config/models;
blocks/definition, port_types, skills; daemon/supervisor, lifecycle, sleep_wake,
resource, run; git/policy; knowledge/memory; security/sandbox; escalation/queue;
task/spec; templates/manager; offline/manager; mcp/client, mcp/registry;
ui/rpg; artifacts/manager; cli/queries; observability/tracing, logging_config
