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
| 3 | one-abstraction-level | 22 | cli/main.py (5), cli/task_runner.py (3), agent/loop.py (3), daemon_ops.py (4), daemon/run.py (2) |
| 4 | single-responsibility | 7 | cli/main.py learnings (4 ops), blocks/registry (3 concerns), team_runner (too many concerns), persist_task_result (4 things) |
| 5 | fail-fast | 11 | sqlite.py (systemic), artifacts/manager.py (3), daemon_ops.py (1), task_runner.py (1), mcp/registry.py (1), api/server.py (2) |
| 6 | DRY | 2 | config/loader.py ↔ toml_utils.py (duplicated TOML writing); cli/main.py default TOML ↔ GuildConfig defaults |

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

## EARLY-EXIT / NESTING (4)

- blocks/port_types.py:96 _basic_schema_check() — depth 4
- orchestration/team_runner.py:342 _try_parse_json() — depth 4
- storage/sqlite.py:641 consolidate_memories() — depth 4
- git/worktree.py:153 _ensure_staging_branch() — depth 4

## CONTEXTUAL LOG MESSAGES (5)

- api/server.py: "API using injected storage", "API storage closed"
- daemon/supervisor.py: "Signal handlers installed", "Original signal handlers restored"
- offline/manager.py: "ollama CLI not found while listing local models"

## MISLEADING

- provider/escalation.py: `generate_with_malformed_recovery` promises 4-step strategy but implements only step 1
- agent/checkpoint.py:87: `provider: object` type hint too loose (should be LLMProvider)

## FILES CONFIRMED CLEAN (40+ files)

agent/completion, stuck, rollback, message, prompts, budget, ratelimit, cost;
provider/base, retry, cli_provider, ollama; storage/protocol; tools/base,
file_ops, shell, search, registry, plugin; permissions/checker; config/models;
blocks/definition, port_types, skills; daemon/supervisor, lifecycle, sleep_wake,
resource, run; git/policy; knowledge/memory; security/sandbox; escalation/queue;
task/spec; templates/manager; offline/manager; mcp/client, mcp/registry;
ui/rpg; artifacts/manager; cli/queries; observability/tracing, logging_config
