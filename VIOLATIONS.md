# Guideline Violations — Full Review Report (2026-05-10)

16 independent review agents audited all 89+ source files against Python + Common guidelines.

---

## REVIEW SCORECARD

| Guideline | Severity | Status | Violations |
|-----------|----------|--------|------------|
| **Python** | | | |
| naming-conventions | HARD | PASS | 0 |
| type-hints-everywhere | HARD | **FAIL** | 40+ (Any abuse, bare generics, no --strict) |
| line-length-100 | HARD | PASS | (enforced by ruff+black) |
| import-order | HARD | PASS | 0 |
| explicit-all-exports | HARD | **FAIL** | 3 modules |
| context-managers | HARD | **FAIL** | 4 violations |
| no-mutable-defaults | HARD | PASS | 0 |
| specific-exceptions | HARD | **FAIL** | 17 broad swallows |
| no-print | HARD | PASS | 0 |
| use-isinstance | HARD | PASS | (enforced by ruff) |
| pyproject-toml-only | HARD | PASS | 0 |
| lock-file-required | HARD | PASS | 0 |
| ruff-docstring-enforcement | HARD | **FAIL** | D rules not in ruff select |
| required-markers | HARD | **FAIL** | 26 test classes missing @pytest.mark.req |
| test-file-naming | HARD | PASS | 0 |
| version-ranges | REC | PASS | 0 |
| minimal-dependencies | REC | PASS | 0 |
| document-dependencies | ADV | PASS | 0 |
| use-dataclasses | REC | PASS | 0 |
| use-pathlib | REC | PASS | 0 |
| composition-over-inheritance | REC | PASS | 0 |
| short-functions | REC | 1 | server.py create_app() 58 lines |
| max-five-params | REC | 4 | loop.py, task_runner.py, sqlite.py (x2) |
| docstring-format | REC | MIXED | Google dominant, NumPy in 2 files |
| **Common** | | | |
| feature-branches | HARD | PASS | (standard workflow) |
| atomic-commits | HARD | PASS | 0 |
| conventional-commits | HARD | PASS | 63/63 (100%) |
| no-artifacts-in-git | HARD | PASS | 0 |
| deployable-main | HARD | PASS | (all commits pass tests) |
| fail-fast | HARD | PARTIAL | 11 (from prior review) |
| no-magic-literals | HARD | PARTIAL | 39 literals (from prior review) |
| centralized-config | HARD | **FAIL** | ~30 scattered constants |
| correct-log-levels | HARD | **FAIL** | 19 misleveled statements |
| contextual-log-messages | HARD | PASS | 5 minor (from prior review) |
| wrap-third-party | HARD | PARTIAL | 3 (from prior review) |
| requirements-coverage | HARD | **FAIL** | 12 requirements uncovered |
| requirements-traceability | HARD | **FAIL** | 4 orphaned markers + regex bug |
| group-by-domain | HARD | PASS | 0 |
| clean-root | REC | PASS | 0 |
| mirrored-test-layout | REC | PASS | 0 |
| readme-summary | HARD | PASS | 0 |
| document-public-api | HARD | PASS | 0 |
| independent-tests | HARD | PASS | 0 |
| no-what-comments | REC | 19 | (from prior review) |
| one-abstraction-level | REC | 22 ACCEPTED | (from prior review) |
| single-responsibility | REC | ACCEPTED | (from prior review) |
| early-exit | REC | PASS | all prior violations fixed |

---

## CRITICAL (correctness/safety)

| # | File | Issue | Guideline |
|---|------|-------|-----------|
| 1 | storage/sqlite.py (~30 methods) | `assert self._db is not None` stripped by `python -O` | fail-fast |
| 2 | orchestration/bus.py:21 | `datetime.now()` (local time) — should be `datetime.now(UTC)` | bug |
| 3 | provider/cli_provider.py:106-121 | Subprocess not killed on timeout — zombie process leak | context-managers |
| 4 | mcp/registry.py:24-25 | Subprocess leaks if `list_tools()` fails after `connect()` | context-managers |
| 5 | api/server.py:311-317 | Storage connect/close around `yield` without try/finally | context-managers |

---

## TYPE HINTS — [type-hints-everywhere] HARD

mypy config has `disallow_untyped_defs = true` but lacks `--strict` mode (`disallow_any_generics`, `disallow_untyped_calls`, etc.).

### Overuse of `Any` (defeats purpose of type hints)

| File | Count | What |
|------|-------|------|
| cli/task_runner.py | 11 | config, store, loop all typed as `Any` instead of GuildConfig/Storage/AgentLoop |
| api/server.py | 11 | `app: Any` (should be FastAPI), `storage: Any` (should be Storage) |
| eval/framework.py:294 | 1 | `row: Any` |

### Bare generics (violates `disallow_any_generics`)

| File | Locations |
|------|-----------|
| config/loader.py | 4 — `_load_toml_file -> dict`, `_deep_merge(base: dict, override: dict) -> dict`, `write_toml_bytes(data: dict)` |
| config/profiles.py | 3 — `_load_toml -> dict`, `_parse_agent_profile(values: dict)`, `_parse_permission_profile(values: dict)` |
| cli/toml_utils.py | 2 — `load_toml -> dict`, `write_toml(data: dict)` |
| blocks/registry.py | 2 — `_parse_block(data: dict)`, `_parse_team(data: dict)` |
| blocks/port_types.py | 2 — `json_schema: dict`, `_basic_schema_check(schema: dict)` |
| storage/sqlite.py | 1 — `params: list` |
| cli/queries.py | 1 — `fetch_pending_questions -> list` |
| agent/checkpoint.py | 1 — `tool_executors: dict` |
| observability/tracing.py | 1 — `details: dict | None` |
| tools/base.py | 1 — `TOOL_SCHEMAS: dict[str, dict]` (inner dict bare) |

### Bare `Callable`

| File | Location |
|------|----------|
| config/loader.py:194 | `callback: Callable` — missing argument/return signature |

---

## EXPLICIT ALL EXPORTS — [explicit-all-exports] HARD

| File | Issue |
|------|-------|
| provider/__init__.py | Missing `__all__` entirely (has no exports but guideline requires it) |
| storage/sqlite.py | 4 public constants not in `__all__`: CONFIDENCE_VALIDATE_INCREMENT, CONFIDENCE_INVALIDATE_DECREMENT, CONFIDENCE_DECAY_DECREMENT, MEMORY_SUMMARY_MAX_CHARS |
| agent/loop.py | `ToolExecutor` type alias not in `__all__` |

---

## CONTEXT MANAGERS — [context-managers] HARD

| # | File:Line | Resource | Issue |
|---|-----------|----------|-------|
| 1 | api/server.py:311-317 | aiosqlite connection | connect()/close() around yield without try/finally |
| 2 | mcp/registry.py:24-25 | subprocess | connect() without cleanup if list_tools() fails |
| 3 | mcp/client.py:44 | subprocess | MCPClient lacks `__aenter__`/`__aexit__` |
| 4 | provider/cli_provider.py:106-121 | subprocess | Process not killed on timeout (zombie leak) |

---

## SPECIFIC EXCEPTIONS — [specific-exceptions] HARD

**Bare `except:` (E722): 0** — ruff clean.

**Broad `except Exception` that swallows without re-raise: 17 violations**

Most common pattern: TOML loading with fallback to empty dict (5 occurrences).

| # | File:Line | What it catches | Recommended narrower type |
|---|-----------|-----------------|---------------------------|
| 1 | blocks/registry.py:158 | Block loading | `(OSError, tomllib.TOMLDecodeError, KeyError, ValueError)` |
| 2 | blocks/skills.py:108 | Skill loading | `(OSError, ValueError, KeyError)` |
| 3 | tools/plugin.py:140 | Plugin loading | `(OSError, tomllib.TOMLDecodeError, KeyError, ValueError)` |
| 4 | config/loader.py:102 | TOML parsing | `(OSError, tomllib.TOMLDecodeError)` |
| 5 | config/profiles.py:145 | TOML parsing | `(OSError, tomllib.TOMLDecodeError)` |
| 6 | provider/ollama.py:30 | Health check | `(ConnectionError, TimeoutError, OSError)` |
| 7 | agent/loop.py:294 | Tool execution | `(OSError, RuntimeError, ValueError, TypeError)` |
| 8 | cli/toml_utils.py:36 | TOML parsing | `(OSError, tomllib.TOMLDecodeError)` |
| 9 | cli/task_runner.py:185 | Learning injection | `(ImportError, OSError, ValueError)` |
| 10 | cli/task_runner.py:247 | Learning extraction | `(ImportError, OSError, ValueError)` |
| 11 | daemon/run.py:71 | Task execution | `(OSError, RuntimeError)` |
| 12 | api/server.py:184 | /api/blocks | `(ImportError, OSError)` |
| 13 | api/server.py:195 | /api/teams | `(ImportError, OSError, tomllib.TOMLDecodeError)` |
| 14 | api/server.py:223 | /api/config | `(OSError, tomllib.TOMLDecodeError, ValueError)` |
| 15 | api/server.py:250 | WebSocket close | `(ConnectionError, OSError, RuntimeError)` |
| 16 | eval/framework.py:141 | Eval harness | `(ConnectionError, TimeoutError, RuntimeError, ValueError)` |
| 17 | offline/manager.py:62 | Connectivity check | `(ConnectionError, TimeoutError, OSError)` |

---

## CENTRALIZED CONFIG — [centralized-config] HARD

GuildConfig covers ~16 fields. **~30+ operational constants scattered across 15 files.**

### Category 1: Timeouts/thresholds (should be in GuildConfig)

| Value | Location |
|-------|----------|
| `SHELL_TIMEOUT_SECONDS = 60` | tools/shell.py:20 |
| `MAX_SHELL_OUTPUT_CHARS = 20_000` | tools/shell.py:21 |
| `_CLI_TIMEOUT_SECONDS = 120` | provider/cli_provider.py:21 |
| `DEFAULT_MAX_TURNS = 50` | agent/loop.py:31 |
| `_SECONDS_PER_TURN_ESTIMATE = 10` | cli/task_runner.py:55 |
| `_MAX_TURNS_CAP = 200` | cli/task_runner.py:57 |
| `_EVAL_MAX_TURNS = 20` | eval/framework.py:37 |
| `_WEBSOCKET_POLL_SECONDS = 2` | api/server.py:23 |
| `DEFAULT_CONTEXT_MAX_TOKENS = 8000` | agent/context.py:26 |
| `DEFAULT_COMPACT_THRESHOLD = 0.7` | agent/context.py:28 |
| `DEFAULT_PRESERVE_RECENT = 4` | agent/context.py:27 |

### Category 2: Resource/scheduling (in local dataclasses, not wired to GuildConfig)

| Value | Location |
|-------|----------|
| `idle_timeout_seconds = 300.0` | daemon/resource.py:52 |
| `cpu_threshold_percent = 80.0` | daemon/resource.py:53 |
| `polite_delay_seconds = 10.0` | daemon/resource.py:54 |
| `sleep_threshold_seconds = 60.0` | daemon/sleep_wake.py:42 |
| `health_check_retries = 5` | daemon/sleep_wake.py:43 |

### Category 3: Retry config (not wired to GuildConfig)

| Value | Location |
|-------|----------|
| `max_retries = 3` | provider/retry.py:24 |
| `initial_delay_seconds = 1.0` | provider/retry.py:25 |
| `backoff_factor = 2.0` | provider/retry.py:26 |
| `max_delay_seconds = 30.0` | provider/retry.py:27 |

### Category 4: Hardcoded ".guild" bypassing GUILD_DIR_NAME constant

| Location |
|----------|
| storage/sqlite.py:149 |
| api/server.py:297 |
| git/worktree.py:47 |

### Possible drift bug

`_DEFAULT_CONFIG_TOML` in cli/main.py writes `default_permission = "autopilot"` but `GuildConfig` defaults to `"ask"`.

---

## CORRECT LOG LEVELS — [correct-log-levels] HARD

**19 misleveled statements:**

### ERROR → should be WARNING (6)

| File:Line | What it logs |
|-----------|-------------|
| daemon/run.py:42 | Task not found in storage (handled, returns early) |
| daemon/run.py:79 | CLI usage message (user error, exits cleanly) |
| daemon/sleep_wake.py:116 | Provider did not recover after retries (handled, returns False) |
| provider/cli_provider.py:116 | CLI provider timed out (raises, caller retries) |
| provider/cli_provider.py:125 | CLI provider non-zero exit (raises, caller retries) |
| daemon/supervisor.py:111 | Agent failed (duplicate of run.py:72, then re-raises) |

### ERROR (via exception()) → should be WARNING (2)

| File:Line | What it logs |
|-----------|-------------|
| agent/loop.py:295 | Tool raised exception (converted to ToolResult, loop continues) |
| escalation/notify.py:120 | Webhook notification failed (side-channel, agent continues) |

### INFO → should be WARNING (4)

| File:Line | What it logs |
|-----------|-------------|
| agent/loop.py:148 | Token budget exceeded (unexpected, cuts work short) |
| agent/loop.py:224 | Stuck detected (unexpected but handled) |
| daemon/lifecycle.py:176 | Cleaned stale lock (indicates prior crash) |
| orchestration/team_runner.py:300 | Skipping failed block (failure, even if policy allows) |

### INFO → should be DEBUG (4)

| File:Line | What it logs |
|-----------|-------------|
| agent/loop.py:260 | Skipping duplicate tool call (internal optimization) |
| daemon/supervisor.py:60 | PID file written (internal plumbing) |
| daemon/supervisor.py:66 | PID file removed (internal plumbing) |
| api/server.py:308 | API using injected storage (test-only path) |

### WARNING → should be DEBUG (2)

| File:Line | What it logs |
|-----------|-------------|
| agent/learning.py:63 | Task has no assigned agent (normal state) |
| agent/learning.py:68 | No messages for agent (normal state) |

### WARNING → should be INFO (1)

| File:Line | What it logs |
|-----------|-------------|
| tools/shell.py:67 | Shell command denied by denylist (policy working as designed) |

---

## RUFF DOCSTRING ENFORCEMENT — [ruff-docstring-enforcement] HARD

The `"D"` rule family is **not included** in ruff's `select` list in pyproject.toml. Rules D100-D107 (missing docstrings) are not enforced. Docstrings exist in practice but there is no automated regression prevention.

**Fix:** Add `"D"` to ruff select and set `convention = "google"` in `[tool.ruff.lint.pydocstyle]`.

---

## REQUIREMENTS TRACEABILITY — [requirements-traceability] + [requirements-coverage] HARD

### Uncovered requirements (12)

| Requirement | Description | Priority |
|-------------|-------------|----------|
| REQ-02.1 | OS-agnostic core functionality | P0 |
| REQ-02.2 | Single install mechanism | P0 |
| REQ-02.3 | Cross-platform file paths / process management | P0 |
| REQ-02.4 | PlatformAdapter interface | P0 |
| REQ-05.4a | Interactive attach | P0 |
| REQ-23.9 | Daemon control socket | P0 |
| REQ-24.6 | GPU/VRAM awareness | P0 |
| REQ-24.7 | Thermal awareness (macOS) | P0 |
| REQ-07.3 | Shared knowledge base between team agents | P1 |
| REQ-04.7a | A2A optional external gateway | P2 |
| REQ-04.24a | Drag-and-drop visual team composer | P2 |
| REQ-05.6/05.7 | Visual team composer / message flow GUI | P3 |

### Orphaned markers (4)

| File | Marker | Problem |
|------|--------|---------|
| tests/test_coverage_gaps2.py:95 | `REQ-14` | Missing sub-ID (should be REQ-14.1) |
| tests/test_coverage_gaps2.py:240 | `REQ-13` | Missing sub-ID |
| tests/test_coverage_gaps3.py:17 | `REQ-25` | Missing sub-ID |
| tests/test_coverage_gaps.py:796 | `REQ-27` | Missing sub-ID |

### Script bug

`req_coverage.py` regex `REQ-(\d+\.\d+)` cannot parse IDs with letter suffixes (REQ-05.4a, REQ-04.7a). Fix: `REQ-(\d+\.\d+[a-z]?)`.

### Missing @pytest.mark.req (26 test classes)

- 10 classes in test_coverage_gaps*.py files (should reference requirements)
- 16 classes in tests/learning/ (third-party assumption tests — may warrant exemption policy)

---

## DOCUMENTATION FORMAT — [docstring-format] REC

Mostly Google style. Two files use NumPy style:
- permissions/checker.py
- security/sandbox.py

---

## REC-LEVEL VIOLATIONS

### [short-functions] (1)

| File:Line | Function | Lines |
|-----------|----------|-------|
| api/server.py:276 | `create_app()` | 58 |

### [max-five-params] (4)

| File:Line | Function | Params (excl self) |
|-----------|----------|-------------------|
| agent/loop.py:67 | `AgentLoop.__init__` | 6 |
| cli/task_runner.py:148 | `run_task` | 6 |
| storage/sqlite.py:334 | `log_decision` | 6 |
| storage/sqlite.py:529 | `insert_question` | 7 |

---

## RETAINED FROM PRIOR REVIEW (unchanged)

### MAGIC LITERALS (39 across 20 files) — [no-magic-literals] HARD

See prior review for full list. Filenames, truncation lengths, identity strings, numeric constants.

### WHAT-COMMENTS (19 across 6 files) — [no-what-comments] REC

- agent/loop.py (6), agent/learning.py (5), eval/framework.py (2), daemon/lifecycle.py (2), observability/replay.py (2), agent/context.py (1)

### WRAP-THIRD-PARTY (3) — [wrap-third-party] HARD

- toml_utils.py: imports typer + rich (CLI framework in utility module)
- knowledge/temporal.py: shells out bypassing safety layer
- escalation/notify.py: raw urllib with broad except

### ONE-ABSTRACTION-LEVEL (22) — ACCEPTED

See prior review. Cost of fix exceeds benefit in 20-30 line functions.

### SINGLE-RESPONSIBILITY — ACCEPTED

See prior review. BlockRegistry, TeamRunner, config_cmd accepted as cohesive.

---

## FIXED IN PRIOR PASS

- DRY (config/loader.py ↔ toml_utils.py): toml_utils now delegates
- Early-exit (4 functions): all flattened
- Misleading (2): docstring + type hint fixed
- SRP (learnings command): extracted `_display_learnings_table()`

---

## FILES CONFIRMED CLEAN (40+ files)

agent/completion, stuck, rollback, message, prompts, budget, ratelimit, cost;
provider/base, retry, cli_provider, ollama; storage/protocol; tools/base,
file_ops, shell, search, registry, plugin; permissions/checker; config/models;
blocks/definition, port_types, skills; daemon/supervisor, lifecycle, sleep_wake,
resource, run; git/policy; knowledge/memory; security/sandbox; escalation/queue;
task/spec; templates/manager; offline/manager; mcp/client, mcp/registry;
ui/rpg; artifacts/manager; cli/queries; observability/tracing, logging_config

---

## PRIORITY FIX ORDER

### P0 — Correctness/Safety (fix immediately)
1. cli_provider.py:106 — kill subprocess on timeout
2. mcp/registry.py:24 — cleanup on list_tools failure
3. api/server.py:311 — try/finally around yield
4. bus.py:21 — datetime.now(UTC)
5. sqlite.py — replace assert with if/raise

### P1 — HARD guideline compliance (fix this sprint)
6. Add `"D"` to ruff select (docstring enforcement)
7. Fix 17 broad exception catches (narrow types)
8. Fix 19 misleveled log statements
9. Fix req_coverage.py regex bug + orphaned markers
10. Add REQ-02 cross-platform tests (biggest coverage gap)
11. Wire ResourceThresholds/RetryConfig/SleepWakeConfig into GuildConfig
12. Add missing `__all__` entries

### P2 — Type safety (fix next sprint)
13. Replace `Any` in task_runner.py and server.py with concrete types
14. Add type parameters to all bare `dict`/`list` annotations
15. Enable mypy `--strict` progressively

### P3 — REC/style (backlog)
16. Consolidate docstring format to Google style
17. Add req markers to 26 test classes
18. Extract create_app() inner lifespan
19. Reduce >5 param functions with config objects
