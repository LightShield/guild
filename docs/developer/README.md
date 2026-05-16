# Guild Developer Guide

## Architecture Overview

Guild uses a three-layer architecture where each layer evolves independently:

- **Layer 1 (Harness):** Process lifecycle, resource management, tools, storage, permissions. This is the foundation that runs agents reliably in the background.
- **Layer 2 (Agent Behaviors):** Decision framework, self-review, learning, escalation, stuck detection, context management. Controls how agents think and recover.
- **Layer 3 (Orchestration):** Teams, decomposition, multi-agent coordination via message bus. Enables multiple agents to collaborate on a task.

## Adding a New Tool

1. Create a function in `src/guild/tools/` that returns a `ToolResult`.
2. Add the tool schema to `TOOL_SCHEMAS` in `src/guild/tools/base.py`.
3. Register the executor in the tool executor dict passed to `AgentLoop`.
4. Add tests in `tests/tools/` tagged with `@pytest.mark.req("REQ-XX.X")`.

Tools receive `(args: dict, working_dir: str | None)` and must return `ToolResult(success=bool, output=str, error=str|None)`.

## Adding a New Provider

1. Subclass `LLMProvider` from `src/guild/provider/base.py`.
2. Implement `async def generate(messages, tools) -> LLMResponse`.
3. Optionally implement `health_check() -> bool` for connectivity checks.
4. Register in `create_provider()` factory in `src/guild/provider/ollama.py`.
5. Add tests in `tests/provider/`.

Providers must return structured `LLMResponse` objects with token counts and optional tool calls.

## Testing Approach

Guild uses Requirements-Based Testing (RBT):

- Every test class is tagged with `@pytest.mark.req("REQ-XX.X")`.
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`.
- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"`.
- Tests mirror the `src/` directory structure under `tests/`.
- Run `python scripts/req_coverage.py` to generate the traceability matrix.
- TDD workflow: write failing tests first, then implement until green.
