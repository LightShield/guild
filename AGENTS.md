# AGENTS.md

This file provides guidance to Codex and other agent runners that read `AGENTS.md`.

The canonical project guide is `CLAUDE.md`. Read and follow it first; it contains the current commands, architecture notes, testing expectations, and repository conventions.

## Global Workflow

Honor any user-level or global agent instructions loaded by the runner, including workflow/mode rules such as caveman mode and context-tool rules such as lean-ctx.

For shell commands, prefer:

```bash
lean-ctx -c <command>
```

Use the `lean-ctx` on `PATH`; do not hardcode a user-specific install path. Fall back to the raw command only when lean-ctx is unavailable, incompatible with the command, the task requires an interactive TTY workflow, or the wrapper would change behavior in a risky way.

Additional guidance for non-Claude agents:

- Prefer the existing Python package layout under `src/guild/` and mirrored tests under `tests/`.
- Use `pytest -m unit` for fast checks when the full suite is not practical.
- Run `ruff check src/ tests/`, `black src/ tests/`, and `mypy src/guild/ --strict` before claiming a broad code change is complete.
- Preserve requirement and acceptance-criteria markers in tests when editing covered behavior.
- Do not treat `.guild/config.toml` as a portable default; it may contain local machine settings.
