# Music Player PoC — Team Composition Demo

This example demonstrates Guild's multi-agent team composition with a generator-evaluator loop.

## Task

> Create a Python music player with real-time notch filter capability using sounddevice and scipy.

## Team Configuration

Two agents in a loop (max 3 iterations):

- **Coder** (`gemma4-4b-dense-med`) — fast model, writes code using file_write tool
- **Verifier** (`gemma4-26b-moe-agent`) — strong model, runs shell commands to test the code

See `team_music.toml`, `coder.toml`, and `verifier.toml` for the block definitions.

## What Happened

```
Iteration 1:
  Coder (4B)    → wrote music_player.py, requirements.txt, README.md
  Verifier (26B) → ran python3 exec check → FAIL (runtime error at line 72)
  
Iteration 2:
  Coder (4B)    → rewrote music_player.py with fix
  Verifier (26B) → ran checks → FAIL (code tries to read nonexistent test file at import time)

Iteration 3:
  Coder (4B)    → rewrote with proper error handling
  Verifier (26B) → all checks pass (compile OK, exec OK, no crash) → PASS
```

Total time: ~15 minutes (dominated by 26B model inference speed on Q4 quantization).

## Key Findings

1. **Error output matters** — the verifier's shell commands produce stderr tracebacks. Guild now includes the full error output (not just "exit code 1") in the feedback to the coder, enabling targeted fixes.

2. **The loop works** — the generator-evaluator pattern correctly rejects broken code and feeds back specific errors.

3. **Per-block model assignment** — the coder runs on the fast 4B model (writes in ~30s), while the verifier uses the stronger 26B model (takes ~2min but catches real errors).

4. **Limitation: logical bugs** — the verifier catches crashes but not wrong argument order. A dedicated unit-test-runner block would improve this.

## Files

| File | Description |
|------|-------------|
| `team_music.toml` | Team composition with loop definition |
| `coder.toml` | Coder block — fast model, tool-use enforced |
| `verifier.toml` | Verifier block — strong model, runs shell checks |
| `output_music_player.py` | Final code produced by the team |
| `output_requirements.txt` | Dependencies file |
| `output_README.md` | User-facing README (generated) |
| `execution_trace.json` | Full conversation trace (6 agents, 57 messages) |

## Running It

```bash
cd your-project/
guild init
guild config --set provider.base_url=http://<ollama-host>:11434

# Copy block definitions
cp examples/music-player-poc/{coder,verifier,team_music}.toml .guild/blocks/

# Run the team
guild team -t music-builder "Create a Python music player with notch filter..."
```
