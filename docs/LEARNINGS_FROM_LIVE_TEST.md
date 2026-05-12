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

1. **Stuck detection too aggressive** — when tests fail with 1 error, agent retries the same shell command 3 times and stuck detector fires. It should recognize "failing test" as a fixable issue and attempt a code fix rather than declaring stuck.
2. **4B model complexity ceiling** — handles 1-3 tool calls well, struggles with 5+ sequential steps
3. **Timeout vs quality tradeoff** — 60s timeout sufficient for simple tasks, needs 120-180s for complex ones

## Corrected Assessment of 26B Model

Initial impression was negative (saw "stuck detected") but upon deeper investigation:
- 26B generated **correct linked_list.py** (all 7 methods work perfectly)
- Generated **17 comprehensive tests** with fixtures, edge cases, empty/single/multiple scenarios
- Only **1 test had a bug** (traversal assertion `current.next.data` should be `current.data`)
- Quality is MUCH higher than 4B — better structure, better test coverage, docstrings, fixtures

The "stuck" behavior was the agent hitting the 1 failing test repeatedly and not being able to fix its own test. This is a **stuck recovery issue**, not a model quality issue.

## Recommendations

- Default timeout should be higher (120-180s) for multi-step tasks
- Stuck recovery should differentiate "test fails" from "command crashes" — for test failures, suggest fixing the test code
- The 26B model produces better code quality — prefer for tasks requiring correctness
- The 4B model is faster for simple tasks (file creation, bug fixes)
- Stuck detection should count unique errors, not repeated identical commands with the same error
