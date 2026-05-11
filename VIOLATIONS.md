# Guideline Compliance Report (2026-05-10)

All HARD guidelines pass. 100% branch coverage. mypy --strict clean.

---

## SCORECARD

| Guideline | Severity | Status |
|-----------|----------|--------|
| **Python** | | |
| naming-conventions | HARD | PASS |
| type-hints-everywhere | HARD | PASS (mypy --strict, 0 errors) |
| line-length-100 | HARD | PASS (ruff + black) |
| import-order | HARD | PASS |
| explicit-all-exports | HARD | PASS |
| context-managers | HARD | PASS |
| no-mutable-defaults | HARD | PASS |
| specific-exceptions | HARD | PASS |
| no-print | HARD | PASS |
| use-isinstance | HARD | PASS |
| pyproject-toml-only | HARD | PASS |
| lock-file-required | HARD | PASS |
| ruff-docstring-enforcement | HARD | PASS (D rules enabled, google convention) |
| required-markers | HARD | PASS |
| test-file-naming | HARD | PASS |
| version-ranges | REC | PASS |
| minimal-dependencies | REC | PASS |
| document-dependencies | ADV | PASS |
| use-dataclasses | REC | PASS |
| use-pathlib | REC | PASS |
| composition-over-inheritance | REC | PASS |
| short-functions | REC | 1 accepted (server.py create_app 58 lines) |
| max-five-params | REC | 4 accepted |
| docstring-format | REC | PASS (Google style throughout) |
| **Common** | | |
| feature-branches | HARD | PASS |
| atomic-commits | HARD | PASS |
| conventional-commits | HARD | PASS (100%) |
| no-artifacts-in-git | HARD | PASS |
| deployable-main | HARD | PASS |
| fail-fast | HARD | PASS |
| no-magic-literals | HARD | PASS (centralized in config/constants.py) |
| centralized-config | HARD | PASS (constants.py + GuildConfig fields) |
| correct-log-levels | HARD | PASS |
| contextual-log-messages | HARD | PASS |
| wrap-third-party | HARD | PASS |
| requirements-coverage | HARD | PASS |
| requirements-traceability | HARD | PASS |
| group-by-domain | HARD | PASS |
| clean-root | REC | PASS |
| mirrored-test-layout | REC | PASS |
| readme-summary | HARD | PASS |
| document-public-api | HARD | PASS |
| independent-tests | HARD | PASS |
| no-what-comments | REC | PASS |
| one-abstraction-level | REC | 22 ACCEPTED |
| single-responsibility | REC | ACCEPTED |
| early-exit | REC | PASS |

---

## METRICS

| Metric | Value |
|--------|-------|
| Source files | 92 |
| Test files | 75+ |
| Total tests | 1361 |
| Branch coverage | 100% |
| mypy --strict | 0 errors |
| ruff check | 0 errors |

---

## ACCEPTED (REC-level, cost of fix exceeds benefit)

### [short-functions] — 1 function

| File | Function | Lines | Justification |
|------|----------|-------|---------------|
| api/server.py:276 | `create_app()` | 58 | App factory with lifespan + route registration. Splitting would scatter setup logic. |

### [max-five-params] — 4 functions

| File | Function | Params | Justification |
|------|----------|--------|---------------|
| agent/loop.py:67 | `AgentLoop.__init__` | 6 | Core loop needs provider, tools, dir, turns, stuck, budget — all essential. |
| cli/task_runner.py:148 | `run_task` | 6 | Entry point plumbing — config, dir, description, permission, timeout, guild_dir. |
| storage/sqlite.py:334 | `log_decision` | 6 | DB insert — all fields are the decision record. |
| storage/sqlite.py:529 | `insert_question` | 7 | DB insert — all fields are the question record. |

### [one-abstraction-level] — 22 violations

CLI commands and entry-point functions that mix 1-2 levels. Extracting 15+ single-call helpers would hurt readability. See prior review for full list.

---

## COMPLETED (previously deferred, now implemented)

| Requirement | Description | Priority | Status |
|-------------|-------------|----------|--------|
| REQ-05.4a | Interactive attach (steer running task) | P2 | Implemented (control socket + attach CLI) |
| REQ-23.9 | Daemon control socket | P2 | Implemented (Unix domain socket, JSON-line protocol) |
| REQ-24.6 | GPU/VRAM awareness | P2 | Implemented (ResourceMonitor + gpu_reader) |
| REQ-24.7 | Thermal awareness (macOS) | P2 | Implemented (ResourceMonitor + thermal_reader) |
| REQ-05.6 | Visual team composer | P3 | Implemented (Svelte + @xyflow drag-and-drop) |
| REQ-05.7 | Agent communication graph | P3 | Implemented (WebSocket-driven live flow view) |

All features built with TDD (tests written first, verified red, then green).
