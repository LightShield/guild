# Guild UI — Session Handoff

## What This Is

The Flow Composer UI (`guild/ui/`) is a visual editor for designing multi-agent workflows. It's a **logicless mirror** of the CLI — every UI action maps to a CLI operation or TOML file write. The UI invents nothing; it renders what the backend already supports.

## Current State

- **102 E2E tests passing** (Playwright, `cd ui && npx playwright test`)
- **Builds cleanly** (`cd ui && npm run build`)
- **Port-based v2 architecture** — flat nodes, no xyflow parentId
- **Python Dev Loop preset** with TDD Implementer block + verification loops
- **Full CRUD API** — blocks and teams read/write TOML files

## Known Bugs (Need Iteration)

These are the kinks remaining from manual testing:

1. **Connections between expanded blocks and external agents may not save correctly in all cases.** The port-to-port mapping (`mapsTo` field) works in simple cases but complex topologies (multiple ports, nested blocks with external connections) haven't been exhaustively verified.

2. **Group boundary drag can feel laggy or desync** — the `onnodedrag` handler tracks position deltas to move children, but xyflow's internal drag state and our manual child-moving can race.

3. **Expanding a saved block may not show internal edges** if the block was saved before the v2 port system (localStorage has old-format blocks from v1 sessions). Clear localStorage to fix, or add migration logic.

4. **The "Split" action always creates 3 sub-agents** — should probably ask the user how many, or default to 2 and let them add more.

5. **Template slots** are defined in data but not visually differentiated on the canvas (no dashed-outline "drop here" visual for unfilled slots).

## Architecture

```
User → UI (Svelte) → API (FastAPI) → Backend (Python) → TOML files
User → CLI (Typer) → Backend (Python) → TOML files
```

Both paths write the SAME files. The UI is a view layer.

### Key Files

| File | Purpose |
|------|---------|
| `ui/src/routes/composer/+page.svelte` | Main canvas logic (1734 lines) |
| `ui/src/lib/components/BlockNode.svelte` | Node rendering with ports |
| `ui/src/lib/components/GroupBoundary.svelte` | Expanded block container |
| `ui/src/lib/api.js` | API client (fetchBlocks, saveTeam, createBlock, etc.) |
| `src/guild/api/server.py` | FastAPI endpoints (CRUD blocks + teams) |
| `src/guild/blocks/definition.py` | Backend data model (BlockDef, PortDef, Connection, TeamDef) |
| `src/guild/blocks/port_types.py` | Port derivation algorithm (`get_composite_ports`) |
| `src/guild/blocks/registry.py` | Block/team TOML loading + validation |
| `docs/ARCHITECTURE_UI.md` | Full mapping of UI → API → Backend → TOML |
| `ui/REQUIREMENTS_v2.md` | Requirements with Three Amigos derivation |

### Core Concepts

**Everything is a Block.** An agent is a leaf block. A group is a composite block. Templates are composites with unfilled slots. There's no type distinction at the system level — just blocks at different abstraction depths.

**Ports solve collapse/expand.** A block has named input/output ports. External edges connect to ports, not directly to children. When you expand a block, edges remap from ports to the internal children those ports `mapsTo`. When you collapse, they remap back. This means **collapse never loses connections**.

**Flat nodes, visual boundaries.** All xyflow nodes are top-level (no `parentId`). When a block is expanded, its children are regular flat nodes positioned within a visual "group-boundary" node (a dashed purple rectangle rendered at low z-index). This eliminates all the nested-parentId bugs we hit in v1.

**Port auto-derivation** matches the backend's `get_composite_ports()`:
- Input ports = child input ports that no internal edge targets
- Output ports = child output ports that no internal edge sources from

### Methodology

We follow the Guidelines system's `/develop` flow:
1. Write requirements (with Three Amigos: user/dev/tester perspectives)
2. Implement
3. Review (run `python3 $GUIDELINES_PATH/src/scripts/review_rules.py --languages frontend,python,common --project-dir .`)
4. Fix findings
5. Verify (E2E tests + coverage check)

The Guidelines repo is at `/Users/ormagen/workspace/private/Guidelines`. It provides:
- Agent personas (`guidelines/agents/*.md`)
- Per-agent rule injection (`guidelines/generated/agent_rules/`)
- Mechanical review (`src/scripts/review_rules.py`)
- Frontend coverage check (`playwright-coverage` tool)

### Key Design Decisions

1. **No localStorage as primary storage.** Custom blocks persist to localStorage for offline use, but the proper path is `POST /api/blocks` → TOML file. The backend is source of truth.

2. **Presets are hardcoded in the UI script.** They should eventually be TOML files loaded via the API (like saved teams), but for now they're inline JavaScript for fast iteration.

3. **Templates have "slots"** (children with `slot: true`) — the visual differentiation and drop-to-fill interaction isn't implemented yet.

4. **Verification loops are modeled as feedback edges** (orange dashed, drawn as a regular xyflow edge from verifier back to doer). The backend's `LoopDef` has `max_iterations` — this should be displayed on the edge label.

## Competition Status

**Deadline:** May 24, 2026

- **Code:** Complete and pushed to `github.com/LightShield/guild`
- **dev.to submission:** `docs/devto_submission.md` — ready to publish
- **Repo visibility:** Currently private — needs `gh repo edit LightShield/guild --visibility public`
- **Tags for submission:** `devchallenge, gemmachallenge, gemma`

## What to Work On Next

Priority order:

1. **Fix remaining connection bugs** — expand a saved block, connect external nodes to internals, collapse, verify nothing is lost. The port `mapsTo` remapping is the critical path.

2. **Visual slot indicators** for templates — dashed outline, "drop agent here" text, type constraint display.

3. **LoopDef display** — show max_iterations on feedback edges, maybe a loop indicator icon.

4. **Split customization** — let user choose how many sub-agents (2-5), name them.

5. **Backend alignment** — make `POST /api/blocks` the primary save path (not localStorage). Load custom blocks from API on mount.

6. **Runtime visualization** (REQ-V2-08) — show active node glow, data flow animation, completion checkmarks. WebSocket already exists (`/ws`).

## Commands

```bash
# Install and develop
cd guild/ui && npm install && npm run dev

# Build for preview
npm run build && npm run preview

# Run E2E tests
npx playwright test e2e/composer.spec.ts --retries=0

# Run frontend review (from project root)
python3 /Users/ormagen/workspace/private/Guidelines/src/scripts/review_rules.py \
  --languages frontend --project-dir .

# Run guild CLI
guild --help
guild serve  # starts API + serves built UI
guild task "description"  # run a task
guild team -t dev "description"  # run a team
```

## Ollama Configuration

Remote Ollama at `192.168.0.111:11434` with models:
- `gemma4-2b-edge-fast` (5.1B Q4) — ultra-light
- `gemma4-4b-dense-med` (8.0B Q4) — default
- `gemma4-26b-moe-agent` (25.8B Q4) — escalation target

```bash
guild config --set provider.base_url=http://192.168.0.111:11434
guild config --set provider.model=gemma4-4b-dense-med
guild config --set escalation.escalation_chain=gemma4-26b-moe-agent
```
