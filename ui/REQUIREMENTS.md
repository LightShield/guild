# Flow Composer UI — Requirements

Extends REQ-05.6 (Visual team composer) from the main REQUIREMENTS.md.

---

## Three Amigos Derivation

**Product perspective:** The flow composer lets users visually design multi-agent workflows — the same ones described in TOML configs today, but interactive. Users should be able to create agents, wire them together, group them into reusable blocks, and inspect what's inside a block. The key differentiator: blocks expand inline so you can see the actual flow structure without leaving the canvas.

**Developer perspective:** This is a SvelteKit + Tailwind + @xyflow/svelte app. State is managed via Svelte 5 runes ($state). The backend provides /api/blocks, /api/teams endpoints. Custom blocks persist to localStorage. The main challenge is that xyflow manages node selection/position internally — we need to track state ourselves via events (onselectionchange, onnodeclick).

**Tester perspective:** We have 14 Playwright E2E tests for the UI already. New requirements must be testable — each AC needs a concrete verify block. Key edge cases: what happens when you expand a block that contains another block? What if you delete a node that's inside an expanded block? What if localStorage is full?

---

## REQ-UI-01: Canvas & Layout

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-01.1 | Dark mode canvas as default | No white backgrounds in any component |
| REQ-UI-01.2 | Main navigation sidebar is collapsible to icon-only mode | Arrow toggle, state persists to localStorage |
| REQ-UI-01.3 | Canvas supports pan (drag) and zoom (scroll) | Standard xyflow controls |
| REQ-UI-01.4 | Adding nodes does NOT refit the viewport | Existing nodes stay in place |
| REQ-UI-01.5 | New nodes are placed in a visible grid pattern near current viewport center | Never offscreen |

### Acceptance Criteria

**REQ-UI-01.1 — Dark mode canvas**
- AC-UI-01.1.1: The xyflow canvas background is dark (#0a0f1a or similar)
  - verify: Open /composer → inspect .svelte-flow element → background-color is dark (not white)
- AC-UI-01.1.2: Minimap, controls, and all overlays match the dark theme
  - verify: Open /composer → minimap and zoom controls have dark backgrounds with gray borders

**REQ-UI-01.2 — Collapsible main sidebar**
- AC-UI-01.2.1: Clicking the collapse arrow reduces sidebar to ~56px (icons only)
  - verify: Click collapse button → sidebar width is ≤ 60px, nav labels are hidden, icons remain visible
- AC-UI-01.2.2: Collapsed state persists across page reload
  - verify: Collapse sidebar, reload page → sidebar is still collapsed

**REQ-UI-01.4 — No viewport jump on add**
- AC-UI-01.4.1: Adding a node via click or drag does not change the viewport position or zoom of other nodes
  - verify: Note position of existing node A, add a new node B → node A's screen position has not changed

**REQ-UI-01.5 — Visible placement**
- AC-UI-01.5.1: A newly added node (via sidebar click) appears within the visible canvas area
  - verify: Add 8 agents via sidebar clicks → all 8 are visible without scrolling/panning

---

## REQ-UI-02: Agent Nodes

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-02.1 | Pre-built agents with default instructions available in sidebar palette | Draggable onto canvas |
| REQ-UI-02.2 | Each node displays: name, role (color-coded badge), role icon | Identifiable at a glance |
| REQ-UI-02.3 | Click a node → right panel opens with editable fields: name, role, model, instructions, verifier config | Full agent editing |
| REQ-UI-02.4 | Pre-built agents show their default instructions when clicked | Not blank |
| REQ-UI-02.5 | "+ Agent" button → form panel to create a custom agent (name, role, model, instructions) | Adds to canvas AND to palette for reuse |
| REQ-UI-02.6 | Verifier decorator: set verifier name, loop condition, max iterations | Shown as dashed orange border + label above node |

### Acceptance Criteria

**REQ-UI-02.3 — Click to edit**
- AC-UI-02.3.1: Clicking a regular (non-block) node on the canvas opens the edit panel on the right
  - verify: Add a "requirements" node, click it → right panel appears with name="requirements", role="planner", instructions field populated
- AC-UI-02.3.2: Changes made in the edit panel update the node immediately on Apply
  - verify: Change name to "req_v2", click Apply → node on canvas shows "req_v2"

**REQ-UI-02.4 — Pre-built instructions visible**
- AC-UI-02.4.1: Clicking a pre-built agent (e.g. "architect") shows its instructions in the edit panel
  - verify: Drag "architect" to canvas, click it → instructions textarea contains "You are a senior technical architect..."

**REQ-UI-02.5 — Create custom agent**
- AC-UI-02.5.1: The "+ Agent" button opens a create form in the right panel
  - verify: Click "+ Agent" → right panel shows fields for name, role dropdown, model dropdown, instructions textarea
- AC-UI-02.5.2: Submitting the form adds the agent to the canvas and to the sidebar palette
  - verify: Fill in name="my_agent", role="coder", submit → node appears on canvas AND "my_agent" appears in sidebar agent list

**REQ-UI-02.6 — Verifier decorator**
- AC-UI-02.6.1: Setting a verifier on a node shows a dashed orange border around it
  - verify: Click node, set verifier="req_verifier", Apply → node has visible dashed orange outline
- AC-UI-02.6.2: Verifier name and max iterations displayed above/near the node
  - verify: Set verifier with max_iterations=5 → label shows "↻ req_verifier (5x)" near the node

---

## REQ-UI-03: Connections

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-03.1 | Drag from output handle (right) to input handle (left) to create a connection | Animated blue edge |
| REQ-UI-03.2 | Connections are directional (visible flow direction) | Animation flows source→target |
| REQ-UI-03.3 | Select edge + Backspace to delete | Standard behavior |

### Acceptance Criteria

**REQ-UI-03.1 — Create connection**
- AC-UI-03.1.1: Dragging from a node's right handle to another node's left handle creates an animated edge
  - verify: Place two nodes, drag from node A's right handle to node B's left handle → a blue animated edge connects them

---

## REQ-UI-04: Blocks (Composites)

### Three Amigos — Block Interaction Refinement

**User perspective:** When I click a block, I want to *peek inside* to see what agents are in there and how they're connected — like opening a folder. Click again to close it (toggle). The block should still be a *thing* on my canvas with a visible boundary. I might want to wire an external connection directly to a specific agent inside the block. Only if I explicitly choose "Ungroup" should it dissolve into free nodes. I also want to create "super groups" — select a group + other agents, save as a new block that contains the original block inside it.

**Developer perspective:** This means a block has two visual states: collapsed (single node) and expanded (shows children inside a container). The block node stays on the canvas — it just grows. Children are rendered with `parentId` (xyflow native subflows). Important constraint: xyflow does NOT support nested parentId (child-of-child). A block inside an expanded block renders as a collapsed node — it cannot be expanded until its parent is collapsed first. "Ungroup" is a separate destructive action.

**Tester perspective:** Edge cases to test:
1. Expand block, click again → must collapse (toggle)
2. Save a group containing another group → super-group with correct recursive agent count
3. Expand super-group → inner block shows as collapsed purple node with correct count
4. Click inner block while parent is expanded → does NOT expand (shows edit panel or tooltip "collapse parent first")
5. Collapse parent, then expand inner block directly → works normally
6. Two blocks with agents sharing the same name → saved block must use unique IDs (no collision)
7. Expand, connect external edge to child, collapse → edge re-routes to block port
8. Expand, ungroup → children become free, parent disappears, edges preserved
9. **Select expanded block + its visible children + other nodes → save as block:** The expanded block must be saved as ONE atomic composite, not as individual children. Children that belong to an expanded parent should be excluded from the selection — the parent represents them.
10. **Select collapsed block + expanded block + free agent → save as block:** The collapsed block is saved as-is (atomic), the expanded block is auto-collapsed before saving (preserving its internal structure), the free agent is saved as a regular node.
11. **Select only children of an expanded block (without the parent) → save as block:** This creates a NEW block from those children — they become a new sub-group. The parent block loses those children (they're extracted).
12. Mixed: some children selected, some not, parent not selected → should warn or refuse (partial extraction is ambiguous)

---

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-04.1 | Shift+drag to multi-select nodes on the canvas | Purple selection rectangle |
| REQ-UI-04.2 | "Save Selection as Block" captures selected nodes AND their internal edges as a named block | Stored in localStorage |
| REQ-UI-04.3 | A saved block placed on canvas renders as a single collapsed node (purple border, agent count badge) | Distinguishable from regular agents |
| REQ-UI-04.4 | **Click a block → expands in-place** showing internal nodes within a visible container boundary (dashed purple border around the group) | Block STAYS on canvas as a parent container — does NOT ungroup |
| REQ-UI-04.4a | **Click an expanded block → collapses it** (toggle behavior) | Click anywhere on container or use header button |
| REQ-UI-04.5 | Expanded block shows internal edges as dashed semi-transparent purple lines within the container | Internal connections visible |
| REQ-UI-04.6 | Internal child nodes are positioned at their saved relative positions inside the container boundary | Same layout as before saving |
| REQ-UI-04.6a | **Nested block inside expanded parent shows as collapsed** — cannot be expanded until parent is collapsed | xyflow limitation: no nested parentId |
| REQ-UI-04.7 | Click expanded block's header/collapse button → collapses back to single node | Container shrinks back to compact representation |
| REQ-UI-04.8 | External edges can connect to specific child nodes inside an expanded block | Drag from outside node into a child — edge connects through the block boundary |
| REQ-UI-04.9 | When collapsing a block that has edges to specific children, those edges re-route to the block's port | Graceful degradation on collapse |
| REQ-UI-04.10 | **"Ungroup" action** (right-click menu or button) dissolves the block into free nodes on the canvas | Destructive — removes the block container, children become top-level nodes |
| REQ-UI-04.11 | Blocks can contain other blocks (nesting) — expanding parent shows child blocks in their collapsed state | Recursive peek |
| REQ-UI-04.12 | Saved blocks appear in sidebar under "Saved Blocks", draggable back onto canvas | Reusable |
| REQ-UI-04.13 | Saved blocks persist in localStorage across sessions | Deletable via × button |
| REQ-UI-04.14 | **Saving a selection that includes an expanded block preserves the block as atomic** — auto-collapse expanded blocks before saving, exclude their visible children from the node list | Expanded children are part of their parent, not separate nodes |
| REQ-UI-04.15 | Saving a selection with a mix of collapsed blocks, expanded blocks, and free agents correctly captures each at its proper abstraction level | Collapsed=atomic, expanded=auto-collapse to atomic, free=individual |

### Acceptance Criteria

**REQ-UI-04.1 — Multi-select**
- AC-UI-04.1.1: Shift+drag draws a selection rectangle and selects all nodes inside it
  - verify: Place 3 nodes in a cluster, Shift+drag around them → all 3 show selected state

**REQ-UI-04.2 — Save as block**
- AC-UI-04.2.1: With 2+ nodes selected, "Save Selection as Block" opens the save form
  - verify: Select 3 connected nodes, click "Save Selection as Block" → form appears asking for block name
- AC-UI-04.2.2: The saved block stores node positions relative to each other and all internal edges
  - verify: Save a block with nodes at (0,0), (200,0), (200,150) connected A→B→C → localStorage entry contains 3 nodes with relative positions and 2 edges

**REQ-UI-04.4 — In-place expansion (NOT ungroup)**
- AC-UI-04.4.1: Clicking a collapsed block visually expands it — the block node grows into a container showing its children inside
  - verify: Click a block → it grows from ~180px to a larger container (dashed purple border) with child nodes visible inside; the block still exists as a single entity on the canvas
- AC-UI-04.4.2: The container has a header showing block name and a collapse button
  - verify: Expanded block shows block name at top and a "▾" or "×" button to collapse
- AC-UI-04.4.3: Internal edges appear as dashed semi-transparent lines between child nodes inside the container
  - verify: Expand a block with edge A→B → a dashed purple edge connects child A to child B within the container
- AC-UI-04.4.4: The block container is still selectable and movable as a single unit (dragging moves all children)
  - verify: Drag the expanded block's header → entire container with children moves together

**REQ-UI-04.7 — Collapse**
- AC-UI-04.7.1: Clicking the collapse button shrinks the block back to a single compact node
  - verify: Expand block, click collapse → block returns to single-node representation at same position

**REQ-UI-04.8 — External edges to children**
- AC-UI-04.8.1: When a block is expanded, dragging an edge from an outside node to a visible child node creates a connection to that child
  - verify: Expand block containing A and B. Drag edge from external node X to child A → edge connects X to A
- AC-UI-04.8.2: The edge visually crosses the block boundary (enters the container)
  - verify: Edge from X to child A is drawn as a line that visually passes through the dashed container border

**REQ-UI-04.9 — Edge re-routing on collapse**
- AC-UI-04.9.1: When collapsing a block that has external edges connected to specific children, those edges re-attach to the block's port
  - verify: Connect X→child_A while expanded, then collapse → edge now shows X→block (not deleted)

**REQ-UI-04.10 — Ungroup**
- AC-UI-04.10.1: An explicit "Ungroup" action (in right-click menu or edit panel) dissolves the block
  - verify: Right-click expanded block → "Ungroup" → container disappears, child nodes become top-level canvas nodes, internal edges become regular edges
- AC-UI-04.10.2: After ungroup, the block no longer exists — children are independent
  - verify: After ungroup, there is no purple container; children can be individually moved and connected

**REQ-UI-04.11 — Nested blocks**
- AC-UI-04.11.1: Expanding a block that contains another block shows the inner block in its collapsed state
  - verify: Block A contains block B + agent C → expand A → see collapsed block B (purple, agent count) and agent C inside A's container

---

## REQ-UI-05: Preset Flows

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-05.1 | "Full Development" preset loads: requirements → architect → (tester ‖ implementer) → reviewer → verificator | With verifiers pre-configured |
| REQ-UI-05.2 | Loading a preset fits viewport to show all nodes | One-time fitView |
| REQ-UI-05.3 | Parallel branches visually positioned at same Y level, offset on X | Clear visual parallel |

### Acceptance Criteria

**REQ-UI-05.1 — Full Development preset**
- AC-UI-05.1.1: Clicking "Full Development" loads 6 nodes with correct connections and verifier decorators
  - verify: Click preset → canvas shows 6 nodes, tester and implementer at same Y level, all connected in the expected flow

---

## REQ-UI-06: Save & Load Flows

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-06.1 | Name field + Save button persists flow to backend (POST /api/teams) | Includes nodes, edges, positions |
| REQ-UI-06.2 | Saved flows listed in sidebar, click to load | Replaces canvas |
| REQ-UI-06.3 | Loading a saved flow fits viewport | One-time fitView |
| REQ-UI-06.4 | Clear button removes all nodes/edges from canvas | Resets state |

### Acceptance Criteria

**REQ-UI-06.1 — Save flow**
- AC-UI-06.1.1: Entering a name and clicking Save sends the flow to the backend
  - verify: Create 2 connected nodes, enter name "my-flow", click Save → POST /api/teams called with correct payload; flow appears in "Saved Flows" list

---

## REQ-UI-07: Help & Discoverability

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-07.1 | "? Shortcuts" toggle at bottom-left of canvas shows legend | Keyboard: Click, Shift+Drag, Backspace, Esc, Scroll. Workflow steps. |
| REQ-UI-07.2 | Empty canvas placeholder with instructions and pointer to preset | Not blank |

### Acceptance Criteria

**REQ-UI-07.1 — Help legend**
- AC-UI-07.1.1: Clicking "? Shortcuts" shows a popup with keyboard bindings and workflow steps
  - verify: Click "? Shortcuts" → popup visible with "Shift + Drag" → "Multi-select nodes" listed

---

## REQ-UI-08: Styling

| ID | Requirement | Notes |
|----|-------------|-------|
| REQ-UI-08.1 | Node cards: rounded-xl, backdrop-blur, shadow, hover:scale[1.02] | Premium feel |
| REQ-UI-08.2 | Role-based colors: planner=purple, coder=blue, tester=green, reviewer=amber, verifier=orange, architect=indigo, implementer=cyan | Consistent |
| REQ-UI-08.3 | Selection rectangle: purple tint | Matches block save theme |
| REQ-UI-08.4 | Block nodes: purple border, "▐▐" icon, agent count | Distinct from regular |
| REQ-UI-08.5 | Expanded block edges: dashed, semi-transparent, purple/blue | Visually subordinate to top-level edges |
| REQ-UI-08.6 | Smooth transitions (150-200ms) on panel open, hover, expand/collapse | Not jarring |
