# GEMINI.md

This repository's canonical agent instructions live in `CLAUDE.md`.

Gemini and other agent CLIs should read `CLAUDE.md` first, then apply any runner-specific constraints from their own environment.

Honor user-level or global agent instructions, including workflow/mode rules such as caveman mode and context-tool rules such as lean-ctx. For shell commands, prefer `lean-ctx -c <command>` from `PATH`; do not hardcode a user-specific install path. Fall back to raw commands only when lean-ctx is unavailable, incompatible with the command, an interactive TTY is required, or the wrapper would risk changing command behavior.
