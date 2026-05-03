# Agent Harness

A locally-focused, cross-platform agent harness for running LLM-powered agent teams with full autonomy, observability, and control.

## Why

Existing agent frameworks have friction: too opinionated, too cloud-dependent, poor permission models, or they babysit you with constant "shall I continue?" prompts. This harness is built to:

- **Run locally first** — Ollama as the default, cloud providers as optional backends
- **Work everywhere** — Windows, macOS, Linux with a single install script
- **Give you control** — Tiered permissions from "nothing allowed" to full autopilot
- **Run autonomously** — Agents work while you're away, stopping only when truly done or truly stuck
- **Scale to teams** — Orchestrator + workers pattern with real-time monitoring

## Status

🚧 **Early development** — Requirements defined, implementation starting.

See [REQUIREMENTS.md](REQUIREMENTS.md) for the full specification (20 requirement areas, prioritized into P0/P1/P2 tiers).

## Quick Start

> Coming soon — install script and first runnable version.

## Project Structure

```
agent-harness/
├── README.md              # This file
├── REQUIREMENTS.md        # Full requirements specification
├── config/                # Default configuration files
│   └── default.toml       # Default harness configuration
├── src/                   # Source code
│   ├── core/              # Harness core — agent lifecycle, message bus, permissions
│   ├── providers/         # LLM provider backends (Ollama, OpenAI, etc.)
│   ├── tools/             # Built-in tools (file, shell, web, search)
│   ├── agents/            # Agent definitions and orchestration logic
│   ├── cli/               # CLI interface
│   └── gui/               # Web-based GUI
├── plugins/               # User-defined tool plugins (drop-in)
├── templates/             # Workflow and team templates
├── tests/                 # Test suite
└── docs/                  # Documentation
```

## License

Private — personal use.
