# Guild

A locally-focused, cross-platform agent harness for running LLM-powered agent teams with full autonomy, observability, and control.

## Why

Existing agent frameworks have friction: too opinionated, too cloud-dependent, poor permission models, or they babysit you with constant "shall I continue?" prompts. Guild is built to:

- **Run locally first** — Ollama as the default, cloud providers as optional backends
- **Work everywhere** — Windows, macOS, Linux with a single install script
- **Give you control** — Tiered permissions from "nothing allowed" to full autopilot
- **Run autonomously** — Agents work while you're away, stopping only when truly done or truly stuck
- **Scale to teams** — Composable agent blocks with drag-and-drop team building

## Status

🚧 **Early development** — Requirements and architecture defined, implementation starting.

See [REQUIREMENTS.md](REQUIREMENTS.md) for the full specification and [ARCHITECTURE.md](ARCHITECTURE.md) for key design decisions.

## Quick Start

> Coming soon — install script and first runnable version.

```bash
guild init                          # Create a new project (.guild/ directory)
guild task "fix the login bug"      # Give the guild a task
guild status                        # See what's happening
guild blocks list                   # List available agent blocks
guild team create dev-loop          # Compose a team
```

## Project Structure

```
guild/
├── README.md              # This file
├── REQUIREMENTS.md        # Full requirements specification
├── ARCHITECTURE.md        # Architecture decisions
├── config/                # Default configuration files
│   └── default.toml       # Default Guild configuration
├── src/                   # Source code
│   ├── core/              # Core — agent lifecycle, message bus, permissions
│   ├── providers/         # LLM provider backends (Ollama, OpenAI, etc.)
│   ├── tools/             # Built-in tools (file, shell, web, search)
│   ├── agents/            # Agent definitions and orchestration logic
│   ├── blocks/            # Block system — atomic, composite, port types
│   ├── cli/               # CLI interface
│   └── gui/               # Web-based GUI (P1)
├── plugins/               # User-defined tool plugins (drop-in)
├── templates/             # Workflow and team templates
├── tests/                 # Test suite
└── docs/                  # Documentation
```

## License

Private — personal use.
