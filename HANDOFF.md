# Guild — Session Handoff

## What This Is

Guild is a free, locally-focused autonomous coding agent harness running on Ollama/Gemma 4 models. Repo: `github.com/LightShield/guild`.

## Current State

- **Tests:** 2284 passing, 0 failures (3 Ollama integration tests skipped — need live server)
- **Mypy --strict:** 0 errors across 108 source files
- **Ruff:** 0 violations
- **Black:** fully formatted
- **All hard guidelines pass** — only recommended-severity items remain (5 modules >300 lines, 3 functions with 6 params, 60 acceptable magic numbers in pricing/Field defaults)

## What Was Done This Session

25 commits of guideline-driven cleanup:
1. Cloned repo, reviewed against Guidelines database (80+ rules)
2. Fixed all hard violations: `.coverage` in git, broad exceptions, magic numbers/strings, stdlib logging → `logger_python`, E2E test reclassification, CLI monolith split, README rewrite, functions >50 lines, >5 params → dataclasses
3. Vendored dependencies (`configsloader`, `logger_python`) into `src/guild/_vendor/` for standalone deployment
4. Fixed 83 test failures from refactor
5. Split `storage/sqlite.py` (895 lines) into 7 entity modules
6. Iterated 3 full evaluation cycles until clean on all hard rules

## Competition: Gemma 4 Challenge

**Deadline:** May 24, 2026, 11:59 PM PDT (8 days from session)

**Submission post draft:** `docs/devto_submission.md` — needs: demo video, verified Ollama model names, publish to dev.to with tags `devchallenge`, `gemmachallenge`, `gemma`

**Angle:** "Start with the weakest model, escalate if stuck" — Gemma 4 4B for fast ops, Gemma 4 31B for complex reasoning, human as last resort. The agent doesn't care if the model can or can't — it adapts.

**What's needed next:**
1. Connect to Ollama with Gemma 4 models, validate the escalation chain works
2. Record demo video (terminal session showing task → escalation → completion)
3. Finalize and publish DEV.to post
4. Make repo public (currently private at `github.com/LightShield/guild`)

## Key Architecture Decisions

- **3-layer design:** Harness (process/tools/storage) → Agent Behaviors (loop/stuck/learning) → Orchestration (teams/blocks/bus)
- **Escalation chain:** configurable via `guild config --set escalation.escalation_chain=gemma-4-31b`
- **"Good neighbor":** `daemon/resource.py` monitors CPU/idle, throttles when user is active
- **Self-improving:** `agent/learning.py` extracts confidence-scored learnings from completed tasks
- **Permission tiers:** nothing / ask / scoped / autopilot + hardcoded-never safety layer

## File Layout

```
src/guild/
├── _vendor/         — Vendored configsloader + logger_python
├── agent/           — Core loop, completion, stuck, rollback, checkpoint, learning, cost, budget
├── provider/        — LLM abstraction (base, Ollama, CLI tool, escalation chain)
├── storage/         — SQLite persistence (split into entity modules)
├── tools/           — Built-in tools (file_read, file_write, shell, search, spawn_agent)
├── permissions/     — 4-tier permission + hardcoded-never
├── config/          — ConfigsLoader models, constants.py (single source of truth)
├── daemon/          — Background execution, resource monitor, sleep/wake, control socket
├── cli/             — Typer CLI (split into task_commands, config_commands, team_commands, daemon_commands)
├── orchestration/   — Message bus, agent spawner, team runner
├── blocks/          — Block definitions, registry, port types, skills
├── git/             — Worktree manager, branch policy
├── knowledge/       — Temporal knowledge, memory index
├── security/        — Sandbox policy
├── escalation/      — Question queue, notification channels
├── observability/   — Structured tracing, log export, session replay
├── task/            — Task specs, verification, status lifecycle
├── artifacts/       — Artifact versioning
├── templates/       — Workflow templates
├── offline/         — Offline-first manager
├── ui/              — RPG mode theming
└── api/             — REST API + A2A gateway
```

## Guidelines Reference

The project follows rules from `/home/ormagen/workspace/private_stash/Guidelines/` — a YAML-based guideline database with `db/common/` (code quality, SOLID, testing, logging, git, docs, project structure) and `db/python/` (style, organization, best practices, error handling, performance, testing, documentation, dependencies, stack). All hard-severity rules now pass.

## Commands

```bash
pip install -e ".[dev]"              # Install
pytest                                # Run tests (2284 pass)
mypy src/guild/ --strict --ignore-missing-imports  # Type check
ruff check src/ tests/               # Lint
black src/ tests/                    # Format
guild --help                         # CLI
python scripts/req_coverage.py       # RTM report
```

## Suggested Skills for Next Session

- If working on Ollama integration/demo: focus on `src/guild/provider/ollama.py` and `src/guild/provider/escalation.py`
- If writing the DEV.to post: refine `docs/devto_submission.md`
- If fixing remaining recommended violations: target modules >300 lines (split `api/server.py` into route modules)
