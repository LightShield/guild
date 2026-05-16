# Guild User Guide

## Installation

```bash
pip install -e ".[dev]"
```

Guild requires Python 3.11+ and a running Ollama instance (local or remote).

## Quick Start

Initialize Guild in your project directory:

```bash
guild init
```

This creates a `.guild/` directory with configuration and local storage.

## Running Tasks

Run a task in the foreground (blocks until complete):

```bash
guild task "refactor the auth module to use dataclasses"
```

Run in the background (daemon mode):

```bash
guild task "add unit tests for the parser" --background
guild ps          # list running tasks
guild attach <id> # interact with a running task
guild kill <id>   # stop a task
```

## Interactive Chat

Start a multi-turn conversation with the agent:

```bash
guild chat
```

## Configuration

Guild uses a layered config system. View or set options:

```bash
guild config                              # show current config
guild config --set provider.model=qwen3   # change the model
guild config --set provider.base_url=http://192.168.0.113:11434
```

Configuration lives in `.guild/config.toml` and supports profiles
for switching between different models or provider settings.
