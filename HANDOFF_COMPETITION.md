# Guild — Gemma 4 Challenge Competition Handoff

## Deadline
**May 24, 2026, 11:59 PM PDT** (4 days from now)

## What This Is
Guild is a free, locally-running autonomous coding agent. Submission for the [Gemma 4 Challenge](https://dev.to/devteam/join-the-gemma-4-challenge-3000-prize-pool-for-ten-winners-23in) on dev.to.

## Current State
- **Code:** Complete, 2307 tests, all guidelines pass
- **Draft post:** `docs/devto_submission.md` — needs demo video/link and final polish
- **Web UI:** Svelte app in `ui/` (SvelteKit + Tailwind)
- **CLI:** Fully functional (`guild task`, `guild chat`, `guild status`, etc.)
- **Repo:** `github.com/LightShield/guild` (currently private — needs to be made public)

## What Needs to Be Done

### 1. Connect to Ollama with Gemma 4 models

```bash
# On the machine with Ollama:
ollama pull gemma4:4b      # or whatever the exact model name is
ollama pull gemma4:31b     # for escalation

# Configure guild:
cd /path/to/guild
pip install -e ".[dev]"
guild init
guild config --set provider.base_url=http://localhost:11434
guild config --set provider.model=gemma4-4b
guild config --set escalation.escalation_chain=gemma4-31b
```

Check model names with `ollama list` — they might be `gemma-4-4b`, `gemma4:4b-it`, etc. Update the config to match exactly.

Verify connection:
```bash
guild task "Say hello" --foreground
```

### 2. Record Demo

The demo should show the **escalation story** — guild starts cheap, escalates when stuck:

**Suggested demo scenario:**
```bash
# Create a small project to work on
mkdir /tmp/demo && cd /tmp/demo && git init
echo "# Demo" > README.md && git add . && git commit -m "init"

# Give guild a task that's moderately complex
guild task "Create a Python CLI that fetches weather data from wttr.in, \
  caches results for 5 minutes, and displays a formatted table. \
  Include error handling and --city flag."
```

This should:
1. Start with gemma4-4b (fast)
2. Potentially get stuck on complex logic or imports
3. Escalate to gemma4-31b
4. Complete the task

**Recording options:**
- Terminal: `asciinema rec demo.cast` then upload to asciinema.org
- Web UI: Start `guild serve` and screen-record the browser
- Both: terminal for authenticity, web UI screenshot for the post

**What to capture:**
- The escalation happening (log line: "Escalating to gemma4-31b (reason: stuck_loop)")
- Task completion
- `guild history` showing the completed task
- Optional: `guild learnings` showing what it learned

### 3. Finalize the dev.to Post

Edit `docs/devto_submission.md`:
- Replace `<!-- TODO: Replace with actual demo video/link -->` with actual link
- Verify model names match what Ollama actually uses
- Add any screenshots from the web UI
- Check all code examples still work with current CLI

Required dev.to tags: `devchallenge`, `gemmachallenge`, `gemma`

### 4. Make Repo Public

On GitHub: `github.com/LightShield/guild` → Settings → Change visibility → Public

### 5. Publish

Post to dev.to with the content from `docs/devto_submission.md`.

## Key Architecture for the Demo

The selling point is the **escalation chain**:

```
gemma4-4b (fast, cheap)
    ↓ stuck? (repeated errors, no progress, looping)
gemma4-31b (heavy reasoning)
    ↓ still stuck?
CLI tools (claude, etc.) — if configured
    ↓ still stuck?
Human (question queue)
```

Config that controls this:
```toml
# .guild/config.toml
[provider]
model = "gemma4-4b"
base_url = "http://localhost:11434"

[escalation]
escalation_chain = "gemma4-31b"
```

The escalation logic is in `src/guild/provider/escalation.py`.

## Commands Reference

```bash
guild init                    # Create .guild/ in current dir
guild task "description"      # Run a task (foreground)
guild task "desc" --background  # Run in background
guild chat                    # Interactive multi-turn
guild status                  # Show project status
guild ps                      # Show running tasks
guild history                 # Past tasks
guild learnings               # Extracted knowledge
guild usage                   # Token/cost summary
guild serve                   # Start REST API + Web UI
guild config --set key=value  # Set config
guild config                  # Show config
```

## Remote Ollama Setup (if Ollama is on a different machine)

```bash
# On Ollama server: ensure it listens on all interfaces
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# On guild machine:
guild config --set provider.base_url=http://<ollama-ip>:11434
```

There's also `scripts/remote-ollama-setup.sh` for LAN setup.

## File Locations

| What | Where |
|------|-------|
| Draft post | `docs/devto_submission.md` |
| Web UI | `ui/` (SvelteKit) |
| Escalation logic | `src/guild/provider/escalation.py` |
| Config models | `src/guild/config/models.py` |
| Agent loop | `src/guild/agent/loop.py` |
| Stuck detection | `src/guild/agent/stuck.py` |
| CLI commands | `src/guild/cli/` |

## What NOT to Change

- Don't refactor the codebase — it passes all guidelines, 2307 tests
- Don't change the architecture — it's documented and stable
- Don't add features — focus on demo + post + publish
- The repo just needs to be public and have a compelling demo
