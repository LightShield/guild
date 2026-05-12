# Learnings from Live Ollama Testing (2026-05-12)

## Setup
- Remote Ollama at 192.168.0.113:11434
- Models: gemma4-4b-dense-med (default), gemma4-26b-moe-agent, gemma4-2b-edge-fast

## What Works Well

1. **Simple single-tool tasks** — "create hello.py that prints X" → instant success
2. **Read-modify-write cycles** — "read file, fix bug, verify" works with 4B model
3. **Tool calling** — file_read, file_write, shell all work correctly
4. **Task persistence** — history, usage stats, audit all recorded correctly
5. **Config system** — model/url switching via `guild config --set` works
6. **Stuck detection** — fires correctly after 3 repeated identical errors

## What Struggles

1. **Multi-file generation + test verification** — creating a module AND its tests AND running them often exceeds timeout or gets stuck in a repair loop
2. **26B model quality** — generated code with typos (e.g., `self.next_node_after_head()` vs `self._next_node_after_head()`) that it can't self-correct
3. **4B model complexity ceiling** — handles 1-3 tool calls well, struggles with 5+ sequential steps
4. **Timeout vs quality tradeoff** — 60s timeout sufficient for simple tasks, insufficient for complex ones

## Recommendations

- Default timeout should be higher (120-180s) for multi-step tasks
- Stuck recovery prompt should suggest "check for typos in method/attribute names" when seeing AttributeError
- For complex tasks, decompose into subtasks (create file → run tests → fix issues) rather than one big prompt
- The 4B model is the best default: fast enough for interactive use, capable enough for focused tasks
- 26B model should be used for planning/decomposition, not direct code generation (too slow + quality issues with agentic tasks)
