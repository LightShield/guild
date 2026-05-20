# Flow Composer UI v2 — Block System Redesign

## Vision

The flow composer is a chip-design-inspired visual editor for multi-agent workflows. Every element is a **block**. Blocks are fractal — they can contain sub-blocks at any depth. The same visual representation serves both design-time (building teams) and runtime (observing execution).

Inspiration: chip/circuit design where you think at the CPU level, the ALU level, or the NAND gate level depending on what you're working on.

---

## Three Amigos

**User perspective:** I want to design agent workflows at different abstraction levels. When I'm thinking high-level, I see "verification loop" as one block. When I need to debug or modify it, I expand it and see the doer + verifier inside with their loop connection. I can connect things to specific internals from outside. When I collapse it back, those connections show as ports on the block. I also want template patterns (like "verification loop") where I just drop agents into pre-wired slots.

**Developer perspective:** The fundamental data model is a recursive graph. A Block has:
- `id`, `name`, `type` (agent | composite | template)
- `ports[]` — named input/output connection points
- `children[]` — sub-blocks (empty for leaf agents)
- `internalEdges[]` — connections between children
- `position` — for rendering

Ports are derived from unconnected internal edges by default, but can be explicitly named and pinned. When a block is collapsed, only ports are visible. When expanded inline, children render inside a container with ports on the boundary.

Key insight: ports solve the collapse/expand problem. An edge from outside connects to a PORT, not directly to a child. The port maps to a specific child internally. This means collapse never loses connections.

**Tester perspective:** Critical scenarios:
1. Create 3 agents A→B→C, save as block X. X has 1 input port (→A) and 1 output port (C→).
2. Expand X, connect external node D to B directly. Collapse X. X now shows a new port for the D connection.
3. Save a "verification loop" template with 2 slots. Drag an agent into slot 1. Verify the connection auto-wires.
4. Block inside block inside block — expand outer, expand inner, verify no visual glitches.
5. Runtime: mark block B as "active" — it should glow/animate. Data flowing on an edge should animate.

---

## Core Concepts

### Block

Everything is a block. A block can be:
- **Leaf** — a single agent (has a prompt, model, tools)
- **Composite** — contains sub-blocks + internal edges
- **Template** — a composite with unfilled slots (drop zones)

### Port

A named connection point on a block's boundary.

- **Input port** — receives data/control flow from outside
- **Output port** — emits data/control flow to outside
- **Auto-derived** — by default, ports are created from unconnected internal edges:
  - An internal edge whose source has no incoming connection from inside → becomes an input port
  - An internal edge whose target has no outgoing connection to inside → becomes an output port
- **Explicit** — user can mark any internal connection point as "externally visible" with a name
- **Dynamic** — when you connect something to an internal node while expanded, on collapse a new port appears

### Edge

A connection between two ports (or between a port and a block's internal node when expanded).

- Top-level edges connect port-to-port between blocks
- When a block is expanded, edges can connect to internal nodes directly
- On collapse, direct-to-internal edges become port-to-port (new port auto-created)

### Template

A pre-wired composite block with **slots** (empty positions for blocks to be dropped into).

- Slots can be typed ("requires: verifier") or untyped
- Dropping a block into a slot auto-connects it per the template's wiring
- Built-in templates: verification loop, parallel branches, sequential pipeline

---

## Requirements

### REQ-V2-01: Block Data Model

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-01.1 | Every element on the canvas is a Block | No distinction between "agent" and "group" — all blocks |
| REQ-V2-01.2 | A Block has: id, name, type (leaf/composite/template), ports[], children[], internalEdges[], position | Core schema |
| REQ-V2-01.3 | Leaf blocks have: model, instructions, tools | Agent configuration |
| REQ-V2-01.4 | Blocks are recursive — a child block can itself be composite | Unlimited nesting depth |
| REQ-V2-01.5 | Blocks are serializable to JSON for localStorage and backend persistence | Round-trip without data loss |

### REQ-V2-02: Ports

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-02.1 | Each block has input ports (left side) and output ports (right side) | Visually on the block boundary |
| REQ-V2-02.2 | **Auto-derived ports:** unconnected first-child input → block input port; unconnected last-child output → block output port | Default: 1 in, 1 out for simple linear chains |
| REQ-V2-02.3 | **Explicit ports:** user can mark any internal node's handle as "externally visible" with a custom name | Right-click or panel action |
| REQ-V2-02.4 | **Dynamic ports:** connecting to an internal node while expanded auto-creates a new port on collapse | Ports grow as needed |
| REQ-V2-02.5 | Ports are displayed on the collapsed block with their names | Like chip pins |
| REQ-V2-02.6 | Edges between blocks connect port-to-port | Never directly to invisible internals |

### REQ-V2-03: Expand / Collapse (Inline)

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-03.1 | Click a block to expand it inline — block grows into a container showing children + internal edges | Container has visible boundary (dashed border) |
| REQ-V2-03.2 | Ports render on the container boundary at their actual positions | Matching where internal connections meet the border |
| REQ-V2-03.3 | External edges visually connect to ports on the boundary, then route internally | "Pass-through" visualization |
| REQ-V2-03.4 | Click expanded block header or boundary to collapse | Toggle behavior |
| REQ-V2-03.5 | Collapsing NEVER loses connections — edges to internals become edges to ports | Core invariant |
| REQ-V2-03.6 | Nested expansion — expand a child block inside an already-expanded parent | Multi-level inline viewing |
| REQ-V2-03.7 | Moving an expanded block moves all its children together | Group drag |

### REQ-V2-04: Editing Inside Blocks

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-04.1 | While a block is expanded, you can add new sub-blocks inside it | Drag from palette into the container |
| REQ-V2-04.2 | While expanded, you can connect internal nodes to each other | Standard edge creation |
| REQ-V2-04.3 | While expanded, you can connect an external node to a specific internal node | Creates a new port on collapse |
| REQ-V2-04.4 | While expanded, you can delete internal nodes and edges | Standard deletion |
| REQ-V2-04.5 | Changes inside a block are immediately reflected in its port configuration | Ports update live |

### REQ-V2-05: Save / Load / Reuse

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-05.1 | Select blocks + save as new composite block | Captures children, edges, derived ports |
| REQ-V2-05.2 | Saved blocks appear in sidebar library | Draggable back onto canvas |
| REQ-V2-05.3 | Placing a saved block creates an independent copy (not a reference) | Editing one doesn't affect others |
| REQ-V2-05.4 | Blocks persist to localStorage | Survive page reload |
| REQ-V2-05.5 | Saving includes ALL state: positions, ports, internal edges, nested blocks | No data loss on round-trip |

### REQ-V2-06: Templates

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-06.1 | A template is a block with unfilled **slots** (placeholder positions) | Visual: dashed outline slot areas |
| REQ-V2-06.2 | Dropping a block into a slot auto-connects it per template wiring | Pre-configured edges activate |
| REQ-V2-06.3 | Slots can be typed (e.g., "requires: verifier role") or untyped | Typed slots reject wrong types |
| REQ-V2-06.4 | Built-in templates: verification loop, parallel split, sequential chain | Shipped with the app |
| REQ-V2-06.5 | Users can save any composite as a template by marking children as slots | "Convert to template" action |

### REQ-V2-07: Splitting / Refactoring

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-07.1 | "Split" action on a leaf block: replaces it with a composite containing N sub-blocks | Preserve external connections via ports |
| REQ-V2-07.2 | "Merge" action on selected blocks: combines into a single composite | Inverse of split |
| REQ-V2-07.3 | Splitting preserves all external edges (they attach to the new block's ports) | Non-destructive refactor |

### REQ-V2-08: Runtime Visualization (Future)

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-08.1 | Active block shows a glow/pulse animation | Which agent is currently executing |
| REQ-V2-08.2 | Data flowing on an edge shows animation direction | Visible data transfer |
| REQ-V2-08.3 | Completed blocks show a checkmark | Progress tracking |
| REQ-V2-08.4 | Failed blocks show error indicator | Problem identification |

### REQ-V2-09: Canvas & UX (Carried from v1)

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-V2-09.1 | Dark mode canvas | Consistent with v1 |
| REQ-V2-09.2 | Collapsible main navigation sidebar | Maximize canvas space |
| REQ-V2-09.3 | Keyboard shortcuts with help legend | Discoverability |
| REQ-V2-09.4 | Smooth transitions (200ms) on expand/collapse/panel | Polish |
| REQ-V2-09.5 | Role-based color coding on blocks | Visual differentiation |
| REQ-V2-09.6 | Preset flows loadable with one click | Quick start |

---

## Implementation Notes

### Port Derivation Algorithm

```
function derivePorts(block):
  if block.type == 'leaf':
    return [InputPort('in'), OutputPort('out')]  // leaf always has 1 in, 1 out
  
  inputs = []
  outputs = []
  for child in block.children:
    for port in child.inputPorts:
      if no internal edge targets this port:
        inputs.append(new InputPort(maps_to=child.port))
    for port in child.outputPorts:
      if no internal edge sources from this port:
        outputs.append(new OutputPort(maps_to=child.port))
  
  // Add any explicitly pinned ports
  inputs += block.explicitInputPorts
  outputs += block.explicitOutputPorts
  
  return inputs + outputs
```

### Collapse Invariant

When collapsing a block:
1. Any edge from external node → internal child becomes external node → block port (port maps to that child)
2. Any edge from internal child → external node becomes block port → external node
3. Internal edges are hidden (stored in block.internalEdges)
4. Ports auto-update to reflect the new connection topology

### xyflow Feasibility

For nested inline expansion, we need either:
- **Option A:** Use xyflow's native parent/child (limited to 1 level, which we've hit)
- **Option B:** Render expanded blocks as SVG overlays manually
- **Option C:** Use a single flat node list but with "group boundary" visual nodes + careful z-indexing

Recommendation: **Option C** — keep all nodes flat in xyflow (no parentId), but render group boundaries as background rectangles. This eliminates the nested-parentId limitation. Expanded children are just regular nodes positioned within the group's visual boundary. The "container" is a visual element, not a structural parent.
