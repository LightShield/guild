# UI ↔ Backend Architecture

The UI is a visual wrapper over the same data the CLI uses. Every UI action maps to a CLI-equivalent operation.

## Data Flow

```
User (UI)  →  API (FastAPI)  →  Backend (Python)  →  Files (TOML)
User (CLI) →  Backend (Python) →  Files (TOML)
```

Both UI and CLI operate on the SAME data files. The UI is not a separate system — it's a view.

## Mapping: UI Concept → API → File

| UI Action | API Endpoint | Backend | File |
|-----------|-------------|---------|------|
| View available agents | GET /api/blocks | `BlockRegistry.list_blocks()` | `.guild/blocks/*.toml` |
| Create an agent | POST /api/blocks | `BlockRegistry.register_block()` | `.guild/blocks/{name}.toml` |
| View teams/flows | GET /api/teams | `config.teams` | `.guild/teams/*.toml` |
| Save a team/flow | POST /api/teams | Writes TOML | `.guild/teams/{name}.toml` |
| Run a team | POST /api/tasks | `guild team -t {name} "..."` | Reads `.guild/teams/{name}.toml` |
| Edit config | POST /api/config | `guild config --set` | `.guild/config.toml` |

## Block Definition (TOML ↔ API ↔ UI)

### File: `.guild/blocks/coder.toml`
```toml
[block]
name = "coder"
role = "coder"
version = "1.0.0"
system_prompt = """You are a senior Python developer..."""
tools = ["file_read", "file_write", "shell", "search", "glob"]
max_retries = 2

[[block.inputs]]
name = "input"
type_tag = "plan"

[[block.outputs]]
name = "output"
type_tag = "code-changes"
```

### API: GET /api/blocks → response item
```json
{
  "name": "coder",
  "role": "coder",
  "version": "1.0.0",
  "system_prompt": "You are a senior Python developer...",
  "tools": ["file_read", "file_write", "shell", "search", "glob"],
  "max_retries": 2,
  "inputs": [{ "name": "input", "type_tag": "plan" }],
  "outputs": [{ "name": "output", "type_tag": "code-changes" }]
}
```

### UI: BlockNode renders
- Name: "coder"
- Role badge: "coder" (blue)
- Left handles: 1 input port named "input" (type: plan)
- Right handles: 1 output port named "output" (type: code-changes)

## Team Definition (TOML ↔ API ↔ UI)

### File: `.guild/teams/dev.toml`
```toml
[team]
name = "dev"
description = "Planner -> Coder -> Reviewer pipeline"
entry_block = "plan"

[team.blocks]
plan = "planner"
code = "coder"
review = "reviewer"

[[team.connections]]
source_block = "plan"
source_port = "output"
target_block = "code"
target_port = "input"

[[team.connections]]
source_block = "code"
source_port = "output"
target_block = "review"
target_port = "input"
```

### API: POST /api/teams (from UI save)
```json
{
  "name": "dev",
  "description": "Planner -> Coder -> Reviewer pipeline",
  "entry_block": "plan",
  "blocks": {
    "plan": { "type": "planner", "position": { "x": 100, "y": 150 } },
    "code": { "type": "coder", "position": { "x": 350, "y": 150 } },
    "review": { "type": "reviewer", "position": { "x": 600, "y": 150 } }
  },
  "connections": [
    { "source_block": "plan", "source_port": "output", "target_block": "code", "target_port": "input" },
    { "source_block": "code", "source_port": "output", "target_block": "review", "target_port": "input" }
  ]
}
```

Note: `position` is UI-only metadata (stored for visual layout, ignored by runtime).

### UI: Canvas renders
- 3 BlockNodes at their positions
- 2 animated edges connecting output ports to input ports
- Edge handles use IDs: `plan__port__output` → `code__port__input`

## Composite Blocks (Saved Selections)

When the user saves a selection as a block, it creates BOTH:
1. A new block TOML file with nested structure
2. The block appears in the registry for reuse

### File: `.guild/blocks/verification_loop.toml`
```toml
[block]
name = "verification_loop"
role = "orchestrator"
version = "1.0.0"
system_prompt = ""

[[block.inputs]]
name = "task"
type_tag = "any"

[[block.outputs]]
name = "result"
type_tag = "any"

[block.composition]
entry_block = "doer"

[block.composition.blocks]
doer = "implementer"
verifier = "code_reviewer"

[[block.composition.connections]]
source_block = "doer"
source_port = "output"
target_block = "verifier"
target_port = "input"

[[block.composition.loops]]
generator_block = "doer"
evaluator_block = "verifier"
max_iterations = 5
```

### UI: Renders as single node with ports
- Input: "task" (left handle)
- Output: "result" (right handle)
- Click to expand → shows doer + verifier + loop edge inside boundary

## Port Derivation (Backend Algorithm)

From `src/guild/blocks/port_types.py::get_composite_ports()`:

```
Exposed inputs = child input ports that have NO incoming internal connection
Exposed outputs = child output ports that have NO outgoing internal connection
```

The UI's `deriveCompositePorts()` implements this same algorithm.

## What the UI Should NOT Do

1. **Store data in localStorage as primary storage** — localStorage is cache/convenience only. The source of truth is `.guild/` files via the API.
2. **Invent its own data model** — use the backend's `BlockDef`, `PortDef`, `Connection`, `TeamDef` exactly.
3. **Support operations the CLI can't** — if you can't do it with `guild team` or a TOML file, the UI shouldn't either.

## What the UI Adds Over CLI

1. **Visual layout** — positions, zoom, pan (UI-only metadata)
2. **Expand/collapse** — visual drill-down into blocks (no backend equivalent needed)
3. **Drag-and-drop** — ergonomic editing (maps to TOML writes)
4. **Real-time monitoring** — WebSocket-driven execution visualization

## API Gaps to Fill

| Missing Endpoint | Purpose | Maps To |
|-----------------|---------|---------|
| POST /api/blocks | Create a new block definition | Write `.guild/blocks/{name}.toml` |
| GET /api/blocks/{name} | Get full block definition (with ports, prompt) | Read + parse TOML |
| PUT /api/blocks/{name} | Update block definition | Rewrite TOML |
| DELETE /api/blocks/{name} | Remove block | Delete TOML file |
| GET /api/teams/{name} | Get full team with positions | Read + parse team TOML |
| DELETE /api/teams/{name} | Remove team | Delete TOML file |

Currently GET /api/blocks only returns `[{"name": "..."}]` — it needs to return the full `BlockDef` with ports so the UI can render them.
