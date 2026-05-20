<script>
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { fetchBlocks, fetchTeams, saveTeam } from '$lib/api.js';
  import BlockNode from '$lib/components/BlockNode.svelte';
  import GroupBoundary from '$lib/components/GroupBoundary.svelte';

  // ===== Core flow state =====
  let nodes = $state([]);
  let edges = $state([]);
  let shouldFitView = $state(false);

  // ===== Sidebar data =====
  let availableBlocks = $state([]);
  let customBlocks = $state([]);
  let teams = $state([]);
  let selectedTeam = $state(null);
  let teamName = $state('');
  let saveMessage = $state('');
  let draggedBlock = $state(null);

  // ===== Right panel state =====
  let panelMode = $state('none'); // 'none' | 'create' | 'edit' | 'save-block'
  let selectedNode = $state(null);
  let showHelp = $state(false);
  let selectedNodeIds = $state(new Set());

  // ===== Create agent form =====
  let newAgentName = $state('');
  let newAgentRole = $state('agent');
  let newAgentModel = $state('gemma4-4b-dense-med');
  let newAgentInstructions = $state('');

  // ===== Edit agent form =====
  let editName = $state('');
  let editRole = $state('');
  let editModel = $state('');
  let editInstructions = $state('');

  // ===== Save as block form =====
  let blockName = $state('');
  let blockDescription = $state('');

  // ===== Expand/collapse tracking =====
  // Maps compositeBlockId -> { block: Block, boundaryNodeId, childNodeIds[], internalEdgeIds[], position }
  let expandedBlocks = $state(new Map());

  const nodeTypes = { block: BlockNode, 'group-boundary': GroupBoundary };

  const roles = ['agent', 'planner', 'architect', 'implementer', 'coder', 'tester', 'reviewer', 'verifier', 'orchestrator'];
  const models = ['gemma4-2b-edge-fast', 'gemma4-4b-dense-med', 'gemma4-26b-moe-agent'];

  const builtinRoles = [
    { name: 'requirements', role: 'planner', description: 'Gather and document requirements', instructions: 'You are a requirements analyst. Given a feature request:\n1. Ask clarifying questions about scope and constraints\n2. Document functional and non-functional requirements\n3. Define acceptance criteria for each requirement\n4. Identify dependencies and risks' },
    { name: 'architect', role: 'architect', description: 'Design system architecture', instructions: 'You are a senior technical architect. Given requirements:\n1. Design the system architecture and component boundaries\n2. Choose appropriate patterns and technologies\n3. Define interfaces between components\n4. Document trade-offs and decisions made' },
    { name: 'implementer', role: 'implementer', description: 'Write implementation code', instructions: 'You are a senior developer. Given a plan:\n1. Implement each step using the available tools\n2. Write clean, well-structured code\n3. Create tests for your implementation\n4. Run the tests to verify they pass' },
    { name: 'tester', role: 'tester', description: 'Write tests (TDD)', instructions: 'You are a test engineer. Given requirements and architecture:\n1. Write comprehensive test cases covering happy path and edge cases\n2. Follow TDD: write tests before implementation exists\n3. Include unit, integration, and E2E tests as appropriate\n4. Ensure 100% branch coverage of critical paths' },
    { name: 'test_runner', role: 'tester', description: 'Execute test suites', instructions: 'You are a CI agent. Your job:\n1. Run the full test suite\n2. Report pass/fail status with details\n3. If tests fail, provide clear error context\n4. Confirm all tests pass before approving' },
    { name: 'code_reviewer', role: 'reviewer', description: 'Review code quality', instructions: 'You are a code reviewer. Given completed work:\n1. Read all created/modified files\n2. Run the tests (shell tool)\n3. Check for bugs, edge cases, security issues\n4. If issues found, explain what needs fixing\n5. If everything passes, confirm with APPROVED' },
    { name: 'verificator', role: 'verifier', description: 'Final verification gate', instructions: 'You are the final verification gate. Check:\n1. All requirements have been implemented\n2. All tests pass\n3. Code follows project conventions\n4. No security vulnerabilities introduced\n5. Documentation is complete\nIf any check fails, route back to the relevant phase.' },
  ];

  // Built-in templates (REQ-V2-06): pre-wired patterns with slots
  const builtinTemplates = [
    {
      name: 'Verification Loop',
      description: 'Agent + verifier with feedback loop (max 5 iterations)',
      role: 'orchestrator',
      children: [
        { id: 'doer', name: 'doer', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 0, y: 0 }, slot: true, slotLabel: 'Drop agent here' },
        { id: 'verifier', name: 'verifier', type: 'leaf', role: 'verifier', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 250, y: 0 }, slot: true, slotLabel: 'Drop verifier here', slotRequires: 'verifier' },
      ],
      internalEdges: [
        { id: 'doer-verifier', sourceChildId: 'doer', sourcePortId: 'out', targetChildId: 'verifier', targetPortId: 'in' },
      ],
      loop: { generator: 'doer', evaluator: 'verifier', maxIterations: 5 },
    },
    {
      name: 'Parallel Split',
      description: 'Fan-out to N agents, sync at end',
      role: 'orchestrator',
      children: [
        { id: 'branch_a', name: 'branch_a', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 0, y: 0 }, slot: true, slotLabel: 'Branch A' },
        { id: 'branch_b', name: 'branch_b', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 0, y: 150 }, slot: true, slotLabel: 'Branch B' },
      ],
      internalEdges: [],
    },
    {
      name: 'Sequential Chain',
      description: 'Linear pipeline: A → B → C',
      role: 'orchestrator',
      children: [
        { id: 'step_1', name: 'step_1', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 0, y: 0 }, slot: true, slotLabel: 'Step 1' },
        { id: 'step_2', name: 'step_2', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 250, y: 0 }, slot: true, slotLabel: 'Step 2' },
        { id: 'step_3', name: 'step_3', type: 'leaf', role: 'agent', ports: [{ id: 'in', name: 'in', direction: 'input', type_tag: 'any' }, { id: 'out', name: 'out', direction: 'output', type_tag: 'any' }], position: { x: 500, y: 0 }, slot: true, slotLabel: 'Step 3' },
      ],
      internalEdges: [
        { id: 'step1-step2', sourceChildId: 'step_1', sourcePortId: 'out', targetChildId: 'step_2', targetPortId: 'in' },
        { id: 'step2-step3', sourceChildId: 'step_2', sourcePortId: 'out', targetChildId: 'step_3', targetPortId: 'in' },
      ],
    },
  ];

  onMount(async () => {
    try { availableBlocks = await fetchBlocks(); } catch { availableBlocks = []; }
    try { teams = await fetchTeams(); } catch { teams = []; }
    if (availableBlocks.length === 0) {
      availableBlocks = builtinRoles;
    }
    const stored = localStorage.getItem('guild-custom-blocks');
    if (stored) {
      try { customBlocks = JSON.parse(stored); } catch { /* ignore */ }
    }
  });

  function persistCustomBlocks() {
    try { localStorage.setItem('guild-custom-blocks', JSON.stringify(customBlocks)); } catch { /* quota exceeded */ }
  }

  // ===== Port Utilities =====

  /** Create a handle ID from a node ID and port ID */
  function makeHandleId(nodeId, portId) {
    return `${nodeId}__port__${portId}`;
  }

  /** Default ports for a leaf block: 1 input, 1 output */
  function defaultLeafPorts(nodeId) {
    return [
      { id: 'in', name: 'in', direction: 'input', type_tag: 'any', handleId: makeHandleId(nodeId, 'in') },
      { id: 'out', name: 'out', direction: 'output', type_tag: 'any', handleId: makeHandleId(nodeId, 'out') },
    ];
  }

  /**
   * Derive ports for a composite block (matches backend get_composite_ports).
   * Input ports = child input ports not targeted by any internal edge.
   * Output ports = child output ports not sourced by any internal edge.
   */
  function deriveCompositePorts(nodeId, children, internalEdges) {
    const targetedPorts = new Set();
    const sourcedPorts = new Set();
    for (const edge of internalEdges) {
      targetedPorts.add(`${edge.targetChildId}__${edge.targetPortId}`);
      sourcedPorts.add(`${edge.sourceChildId}__${edge.sourcePortId}`);
    }

    const inputs = [];
    const outputs = [];

    for (const child of children) {
      const childPorts = child.ports || defaultLeafPorts(child.id);
      for (const port of childPorts) {
        if (port.direction === 'input' && !targetedPorts.has(`${child.id}__${port.id}`)) {
          inputs.push({
            id: `${child.id}.${port.id}`,
            name: `${child.name}.${port.name}`,
            direction: 'input',
            type_tag: port.type_tag || 'any',
            handleId: makeHandleId(nodeId, `${child.id}.${port.id}`),
            mapsTo: { childId: child.id, portId: port.id },
          });
        }
        if (port.direction === 'output' && !sourcedPorts.has(`${child.id}__${port.id}`)) {
          outputs.push({
            id: `${child.id}.${port.id}`,
            name: `${child.name}.${port.name}`,
            direction: 'output',
            type_tag: port.type_tag || 'any',
            handleId: makeHandleId(nodeId, `${child.id}.${port.id}`),
            mapsTo: { childId: child.id, portId: port.id },
          });
        }
      }
    }
    return [...inputs, ...outputs];
  }

  /** Build a Block data structure from node data */
  function buildBlock(nodeId, data) {
    const block = {
      id: nodeId,
      name: data.blockName || 'agent',
      type: data.type || 'leaf',
      role: data.role || 'agent',
      model: data.model,
      instructions: data.instructions,
      ports: data.ports || [],
      children: data.children || [],
      internalEdges: data.internalEdges || [],
    };
    return block;
  }

  // ===== Drag and Drop =====

  function onDragStart(event, block) {
    draggedBlock = block;
    event.dataTransfer.setData('application/guild-block', JSON.stringify(block));
    event.dataTransfer.effectAllowed = 'move';
  }

  function onDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }

  function onDrop(event) {
    event.preventDefault();
    let block = draggedBlock;
    if (!block) {
      try { block = JSON.parse(event.dataTransfer.getData('application/guild-block')); } catch { return; }
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    const position = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    placeBlockOnCanvas(block, position);
    draggedBlock = null;
  }

  // ===== Node Creation =====

  function placeBlockOnCanvas(block, position) {
    const id = `${block.name}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const isComposite = !!(block.children && block.children.length > 0);

    const ports = isComposite
      ? deriveCompositePorts(id, block.children, block.internalEdges || [])
      : defaultLeafPorts(id);

    const newNode = {
      id,
      type: 'block',
      position,
      data: {
        blockName: block.name,
        type: isComposite ? 'composite' : 'leaf',
        role: block.role || 'agent',
        model: block.model || 'gemma4-4b-dense-med',
        instructions: block.instructions || '',
        ports,
        children: isComposite ? block.children : [],
        internalEdges: isComposite ? (block.internalEdges || []) : [],
        childCount: isComposite ? countAgents(block.children) : 0,
      },
    };
    nodes = [...nodes, newNode];
  }

  function addBlockFromSidebar(block) {
    const col = nodes.filter((n) => n.type === 'block').length % 4;
    const row = Math.floor(nodes.filter((n) => n.type === 'block').length / 4);
    placeBlockOnCanvas(block, { x: 80 + col * 240, y: 80 + row * 180 });
  }

  // ===== Expand / Collapse (Flat Nodes + Visual Boundaries) =====

  const BOUNDARY_PADDING_X = 40;
  const BOUNDARY_PADDING_TOP = 60;
  const BOUNDARY_PADDING_BOTTOM = 40;
  const CHILD_SPACING_X = 240;
  const CHILD_SPACING_Y = 140;
  const CHILD_COLS = 3;

  function expandBlock(blockNodeId) {
    const blockNode = nodes.find((n) => n.id === blockNodeId);
    if (!blockNode || blockNode.data.type !== 'composite') return;
    if (expandedBlocks.has(blockNodeId)) return;

    const { children, internalEdges, ports } = blockNode.data;
    const blockPos = blockNode.position;

    // Create child nodes as flat top-level nodes
    const childNodeIds = [];
    const newChildNodes = children.map((child, index) => {
      const childNodeId = `${blockNodeId}__child__${child.id}`;
      childNodeIds.push(childNodeId);

      const col = index % CHILD_COLS;
      const row = Math.floor(index / CHILD_COLS);
      const relX = child.position?.x ?? (BOUNDARY_PADDING_X + col * CHILD_SPACING_X);
      const relY = child.position?.y ?? (BOUNDARY_PADDING_TOP + row * CHILD_SPACING_Y);

      const isChildComposite = !!(child.children && child.children.length > 0);
      const childPorts = isChildComposite
        ? deriveCompositePorts(childNodeId, child.children, child.internalEdges || [])
        : defaultLeafPorts(childNodeId);

      return {
        id: childNodeId,
        type: 'block',
        position: { x: blockPos.x + relX, y: blockPos.y + relY },
        data: {
          blockName: child.name,
          type: isChildComposite ? 'composite' : 'leaf',
          role: child.role || 'agent',
          model: child.model || 'gemma4-4b-dense-med',
          instructions: child.instructions || '',
          ports: childPorts,
          children: child.children || [],
          internalEdges: child.internalEdges || [],
          childCount: isChildComposite ? countAgents(child.children) : 0,
        },
        zIndex: 10,
      };
    });

    // Calculate boundary size from children
    let maxX = 0, maxY = 0;
    for (const child of newChildNodes) {
      maxX = Math.max(maxX, child.position.x - blockPos.x + 200);
      maxY = Math.max(maxY, child.position.y - blockPos.y + 80);
    }
    const boundaryWidth = Math.max(maxX + BOUNDARY_PADDING_X + 20, 400);
    const boundaryHeight = Math.max(maxY + BOUNDARY_PADDING_BOTTOM + 20, 250);

    // Create boundary node (low z-index, behind children)
    const boundaryNodeId = `${blockNodeId}__boundary`;
    const boundaryNode = {
      id: boundaryNodeId,
      type: 'group-boundary',
      position: { ...blockPos },
      style: `width: ${boundaryWidth}px; height: ${boundaryHeight}px;`,
      data: {
        blockName: blockNode.data.blockName,
        childCount: blockNode.data.childCount,
        ports: ports,
        onCollapse: () => collapseBlock(blockNodeId),
      },
      zIndex: 1,
    };

    // Create internal edges (dashed purple)
    const internalEdgeIds = [];
    const newInternalEdges = (internalEdges || []).map((ie) => {
      const edgeId = `${blockNodeId}__ie__${ie.id || ie.sourceChildId + '-' + ie.targetChildId}`;
      internalEdgeIds.push(edgeId);
      const sourceNodeId = `${blockNodeId}__child__${ie.sourceChildId}`;
      const targetNodeId = `${blockNodeId}__child__${ie.targetChildId}`;
      return {
        id: edgeId,
        source: sourceNodeId,
        target: targetNodeId,
        sourceHandle: makeHandleId(sourceNodeId, ie.sourcePortId),
        targetHandle: makeHandleId(targetNodeId, ie.targetPortId),
        animated: true,
        style: 'stroke: #a78bfa; stroke-width: 2px; stroke-dasharray: 5 3; opacity: 0.7;',
      };
    });

    // Remap external edges: edges connected to the block's ports now connect to child ports
    const updatedEdges = edges.map((e) => {
      // Edge targeting this block
      if (e.target === blockNodeId && e.targetHandle) {
        const port = ports.find((p) => p.handleId === e.targetHandle && p.mapsTo);
        if (port) {
          const childNodeId = `${blockNodeId}__child__${port.mapsTo.childId}`;
          return { ...e, target: childNodeId, targetHandle: makeHandleId(childNodeId, port.mapsTo.portId) };
        }
      }
      // Edge sourcing from this block
      if (e.source === blockNodeId && e.sourceHandle) {
        const port = ports.find((p) => p.handleId === e.sourceHandle && p.mapsTo);
        if (port) {
          const childNodeId = `${blockNodeId}__child__${port.mapsTo.childId}`;
          return { ...e, source: childNodeId, sourceHandle: makeHandleId(childNodeId, port.mapsTo.portId) };
        }
      }
      return e;
    });

    // Store expansion state
    const newExpanded = new Map(expandedBlocks);
    newExpanded.set(blockNodeId, {
      block: blockNode.data,
      position: { ...blockPos },
      boundaryNodeId,
      childNodeIds,
      internalEdgeIds,
    });
    expandedBlocks = newExpanded;

    // Remove the block node, add boundary + children
    nodes = [
      ...nodes.filter((n) => n.id !== blockNodeId),
      boundaryNode,
      ...newChildNodes,
    ];
    edges = [...updatedEdges, ...newInternalEdges];
  }

  function collapseBlock(blockNodeId) {
    const state = expandedBlocks.get(blockNodeId);
    if (!state) return;

    const { block, position, boundaryNodeId, childNodeIds, internalEdgeIds } = state;

    // Recursively collapse any expanded children first
    for (const childId of childNodeIds) {
      if (expandedBlocks.has(childId)) {
        collapseBlock(childId);
      }
    }

    const childIdSet = new Set(childNodeIds);
    const internalEdgeIdSet = new Set(internalEdgeIds);

    // Rebuild ports (in case children positions changed we keep original ports)
    const ports = block.ports;

    // Remap external edges back: edges connected to children re-route to block ports
    const updatedEdges = edges
      .filter((e) => !internalEdgeIdSet.has(e.id))
      .map((e) => {
        // Edge targeting a child of this block
        if (childIdSet.has(e.target)) {
          const port = ports.find((p) => p.mapsTo && `${blockNodeId}__child__${p.mapsTo.childId}` === e.target);
          if (port) {
            return { ...e, target: blockNodeId, targetHandle: port.handleId };
          }
        }
        // Edge sourcing from a child of this block
        if (childIdSet.has(e.source)) {
          const port = ports.find((p) => p.mapsTo && `${blockNodeId}__child__${p.mapsTo.childId}` === e.source);
          if (port) {
            return { ...e, source: blockNodeId, sourceHandle: port.handleId };
          }
        }
        return e;
      });

    // Get boundary position (may have been dragged)
    const boundaryNode = nodes.find((n) => n.id === boundaryNodeId);
    const restorePos = boundaryNode ? boundaryNode.position : position;

    // Recreate the block node
    const restoredNode = {
      id: blockNodeId,
      type: 'block',
      position: restorePos,
      data: { ...block, ports: ports.map((p) => ({ ...p, handleId: makeHandleId(blockNodeId, p.id) })) },
    };

    // Remove boundary + children, add block back
    nodes = [
      ...nodes.filter((n) => n.id !== boundaryNodeId && !childIdSet.has(n.id)),
      restoredNode,
    ];
    edges = updatedEdges;

    // Remove from expanded map
    const newExpanded = new Map(expandedBlocks);
    newExpanded.delete(blockNodeId);
    expandedBlocks = newExpanded;
  }

  // ===== Node Click Handler =====

  function onNodeClick({ node, event }) {
    if (!node) return;

    // Shift-click = multi-select, do not expand/edit
    if (event?.shiftKey) return;

    // Click on boundary -> collapse
    if (node.type === 'group-boundary') {
      if (node.data.onCollapse) node.data.onCollapse();
      return;
    }

    if (node.type !== 'block') return;

    // Composite block -> expand it
    if (node.data.type === 'composite') {
      if (expandedBlocks.has(node.id)) {
        // Already expanded somehow (shouldn't happen since node is removed), ignore
        return;
      }
      expandBlock(node.id);
      return;
    }

    // Leaf block -> open edit panel
    selectedNode = node;
    editName = node.data.blockName || '';
    editRole = node.data.role || 'agent';
    editModel = node.data.model || 'gemma4-4b-dense-med';
    editInstructions = node.data.instructions || '';
    panelMode = 'edit';
  }

  // ===== Selection Tracking =====

  function onSelectionChange({ nodes: selectedNodes }) {
    selectedNodeIds = new Set((selectedNodes || []).map((n) => n.id));
  }

  // ===== Create Agent =====

  function openCreatePanel() {
    panelMode = 'create';
    newAgentName = '';
    newAgentRole = 'agent';
    newAgentModel = 'gemma4-4b-dense-med';
    newAgentInstructions = '';
  }

  function createAgent() {
    if (!newAgentName.trim()) return;
    const block = {
      name: newAgentName.trim(),
      role: newAgentRole,
      model: newAgentModel,
      instructions: newAgentInstructions,
    };
    addBlockFromSidebar(block);
    availableBlocks = [...availableBlocks, block];
    panelMode = 'none';
  }

  // ===== Edit Agent =====

  function applyEdit() {
    if (!selectedNode) return;
    const nodeId = selectedNode.id;
    nodes = nodes.map((n) => {
      if (n.id === nodeId) {
        return {
          ...n,
          data: {
            ...n.data,
            blockName: editName,
            role: editRole,
            model: editModel,
            instructions: editInstructions,
          },
        };
      }
      return n;
    });
    panelMode = 'none';
    selectedNode = null;
  }

  function deleteNode() {
    if (!selectedNode) return;
    const nodeId = selectedNode.id;
    edges = edges.filter((e) => e.source !== nodeId && e.target !== nodeId);
    nodes = nodes.filter((n) => n.id !== nodeId);
    panelMode = 'none';
    selectedNode = null;
  }

  // ===== Save as Block =====

  function getSelectedNodes() {
    return nodes.filter((n) => selectedNodeIds.has(n.id) && n.type === 'block');
  }

  function openSaveBlockPanel() {
    const selected = getSelectedNodes();
    if (selected.length < 2) {
      saveMessage = `Select 2+ nodes (currently ${selected.length} selected)`;
      setTimeout(() => (saveMessage = ''), 3000);
      return;
    }
    panelMode = 'save-block';
    blockName = '';
    blockDescription = '';
  }

  function saveAsBlock() {
    if (!blockName.trim()) return;
    const selected = getSelectedNodes();
    if (selected.length < 2) return;

    // Collapse any expanded children in the selection
    for (const n of selected) {
      if (expandedBlocks.has(n.id)) {
        collapseBlock(n.id);
      }
    }

    // Re-fetch after potential collapse
    const finalSelected = getSelectedNodes();
    if (finalSelected.length < 2) return;

    // Normalize positions relative to the top-left
    const minX = Math.min(...finalSelected.map((n) => n.position.x));
    const minY = Math.min(...finalSelected.map((n) => n.position.y));

    const selectedIds = new Set(finalSelected.map((n) => n.id));

    // Build children array for the composite block
    const children = finalSelected.map((n) => ({
      id: n.data.blockName || n.id,
      name: n.data.blockName || 'agent',
      type: n.data.type || 'leaf',
      role: n.data.role || 'agent',
      model: n.data.model,
      instructions: n.data.instructions,
      ports: (n.data.ports || []).map((p) => ({ id: p.id, name: p.name, direction: p.direction, type_tag: p.type_tag })),
      children: n.data.children || [],
      internalEdges: n.data.internalEdges || [],
      position: { x: n.position.x - minX, y: n.position.y - minY },
    }));

    // Build a mapping from canvas node IDs to child IDs
    const nodeIdToChildId = {};
    finalSelected.forEach((n, i) => {
      nodeIdToChildId[n.id] = children[i].id;
    });

    // Capture internal edges (edges between selected nodes) with port IDs from handles
    const internalEdges = edges
      .filter((e) => selectedIds.has(e.source) && selectedIds.has(e.target))
      .map((e) => {
        const sourcePortId = e.sourceHandle?.split('__port__')[1] || 'out';
        const targetPortId = e.targetHandle?.split('__port__')[1] || 'in';
        return {
          id: `${nodeIdToChildId[e.source]}-${nodeIdToChildId[e.target]}`,
          sourceChildId: nodeIdToChildId[e.source],
          sourcePortId,
          targetChildId: nodeIdToChildId[e.target],
          targetPortId,
        };
      });

    // Derive ports for the composite block
    const ports = deriveCompositePorts(`composite-${Date.now()}`, children, internalEdges);

    const compositeBlock = {
      name: blockName.trim(),
      role: 'orchestrator',
      description: blockDescription || `Composite: ${children.map((c) => c.name).join(' + ')}`,
      children,
      internalEdges,
      ports,
    };

    customBlocks = [...customBlocks, compositeBlock];
    persistCustomBlocks();

    // Also save to backend if available (fire and forget)
    import('$lib/api.js').then(({ createBlock }) => {
      createBlock({
        name: compositeBlock.name,
        role: compositeBlock.role,
        system_prompt: '',
        inputs: ports.filter(p => p.direction === 'input').map(p => ({ name: p.name, type_tag: p.type_tag })),
        outputs: ports.filter(p => p.direction === 'output').map(p => ({ name: p.name, type_tag: p.type_tag })),
        children: children.map(c => ({ name: c.id, type: c.role })),
        internal_edges: internalEdges,
      }).catch(() => { /* backend not available */ });
    }).catch(() => {});
    panelMode = 'none';
    saveMessage = `Block "${blockName}" saved`;
    setTimeout(() => (saveMessage = ''), 3000);
  }

  function deleteCustomBlock(index) {
    customBlocks = customBlocks.filter((_, i) => i !== index);
    persistCustomBlocks();
  }

  // ===== Connection Drawing =====

  function onConnect(connection) {
    const newEdge = {
      id: `e-${connection.source}-${connection.target}-${Date.now()}`,
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle,
      targetHandle: connection.targetHandle,
      animated: true,
      style: 'stroke: #38bdf8; stroke-width: 2px;',
    };
    edges = [...edges, newEdge];
  }

  // ===== Keyboard Handling =====

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      panelMode = 'none';
      selectedNode = null;
    }
  }

  function deleteSelected() {
    if (selectedNodeIds.size === 0) return;
    // Clean up any expanded blocks being deleted
    for (const nodeId of selectedNodeIds) {
      if (expandedBlocks.has(nodeId)) {
        collapseBlock(nodeId);
      }
    }
    edges = edges.filter((e) => !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target));
    nodes = nodes.filter((n) => !selectedNodeIds.has(n.id));
    selectedNodeIds = new Set();
  }

  // ===== Count agents recursively =====

  function countAgents(children) {
    let total = 0;
    for (const child of children || []) {
      if (child.children && child.children.length > 0) {
        total += countAgents(child.children);
      } else {
        total += 1;
      }
    }
    return total;
  }

  // ===== Preset Flow =====

  function loadPresetFlow() {
    const presetNodes = [
      { id: 'req', name: 'requirements', role: 'planner', model: 'gemma4-4b-dense-med', instructions: builtinRoles[0].instructions },
      { id: 'arch', name: 'architect', role: 'architect', model: 'gemma4-4b-dense-med', instructions: builtinRoles[1].instructions },
      { id: 'tester', name: 'tester', role: 'tester', model: 'gemma4-4b-dense-med', instructions: builtinRoles[3].instructions },
      { id: 'impl', name: 'implementer', role: 'implementer', model: 'gemma4-4b-dense-med', instructions: builtinRoles[2].instructions },
      { id: 'review', name: 'code_reviewer', role: 'reviewer', model: 'gemma4-26b-moe-agent', instructions: builtinRoles[5].instructions },
      { id: 'verif', name: 'verificator', role: 'verifier', model: 'gemma4-26b-moe-agent', instructions: builtinRoles[6].instructions },
    ];

    const positions = [
      { x: 50, y: 150 }, { x: 300, y: 150 }, { x: 550, y: 100 },
      { x: 550, y: 250 }, { x: 800, y: 150 }, { x: 1050, y: 150 },
    ];

    nodes = presetNodes.map((pn, i) => ({
      id: pn.id,
      type: 'block',
      position: positions[i],
      data: {
        blockName: pn.name,
        type: 'leaf',
        role: pn.role,
        model: pn.model,
        instructions: pn.instructions,
        ports: defaultLeafPorts(pn.id),
        children: [],
        internalEdges: [],
        childCount: 0,
      },
    }));

    edges = [
      { id: 'e-req-arch', source: 'req', target: 'arch', sourceHandle: makeHandleId('req', 'out'), targetHandle: makeHandleId('arch', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-tester', source: 'arch', target: 'tester', sourceHandle: makeHandleId('arch', 'out'), targetHandle: makeHandleId('tester', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-impl', source: 'arch', target: 'impl', sourceHandle: makeHandleId('arch', 'out'), targetHandle: makeHandleId('impl', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-tester-review', source: 'tester', target: 'review', sourceHandle: makeHandleId('tester', 'out'), targetHandle: makeHandleId('review', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-impl-review', source: 'impl', target: 'review', sourceHandle: makeHandleId('impl', 'out'), targetHandle: makeHandleId('review', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-review-verif', source: 'review', target: 'verif', sourceHandle: makeHandleId('review', 'out'), targetHandle: makeHandleId('verif', 'in'), animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
    ];

    teamName = 'full-development';
    selectedTeam = { name: 'full-development' };
    shouldFitView = true;
    requestAnimationFrame(() => { shouldFitView = false; });
  }

  // ===== Load Team =====

  function loadTeam(team) {
    selectedTeam = team;
    teamName = team.name;
    const teamNodes = [];
    const teamEdges = [];
    let x = 50;
    for (const [instance, blockType] of Object.entries(team.blocks || {})) {
      const isObj = typeof blockType === 'object';
      const role = isObj ? blockType.role || 'agent' : 'agent';
      const position = (isObj && blockType.position) ? blockType.position : { x, y: 150 + (teamNodes.length % 3) * 150 };
      const nodeId = instance;
      teamNodes.push({
        id: nodeId,
        type: 'block',
        position,
        data: {
          blockName: isObj ? blockType.name || instance : instance,
          type: 'leaf',
          role,
          model: (isObj && blockType.model) || 'gemma4-4b-dense-med',
          instructions: (isObj && blockType.instructions) || '',
          ports: defaultLeafPorts(nodeId),
          children: [],
          internalEdges: [],
          childCount: 0,
        },
      });
      if (!isObj || !blockType.position) x += 250;
    }
    for (const conn of team.connections || []) {
      teamEdges.push({
        id: `${conn.source_block}-${conn.target_block}`,
        source: conn.source_block,
        target: conn.target_block,
        sourceHandle: makeHandleId(conn.source_block, conn.source_port || 'out'),
        targetHandle: makeHandleId(conn.target_block, conn.target_port || 'in'),
        animated: true,
        style: 'stroke: #38bdf8; stroke-width: 2px;',
      });
    }
    nodes = teamNodes;
    edges = teamEdges;
    shouldFitView = true;
    requestAnimationFrame(() => { shouldFitView = false; });
  }

  // ===== Save Flow =====

  async function handleSave() {
    if (!teamName.trim()) { saveMessage = 'Enter a flow name'; return; }
    try {
      await saveTeam(teamName.trim(), nodes.filter((n) => n.type === 'block'), edges);
      saveMessage = `Saved "${teamName}"`;
      teams = await fetchTeams();
      setTimeout(() => (saveMessage = ''), 3000);
    } catch (e) {
      saveMessage = `Error: ${e.message}`;
    }
  }

  function clearCanvas() {
    nodes = [];
    edges = [];
    expandedBlocks = new Map();
    selectedTeam = null;
    teamName = '';
    saveMessage = '';
    panelMode = 'none';
    selectedNode = null;
  }
</script>

<svelte:head>
  <title>Guild - Flow Composer</title>
</svelte:head>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="h-[calc(100vh-4rem)] flex" onkeydown={onKeyDown}>
  <!-- Left sidebar -->
  <div class="w-72 bg-gray-900/50 border-r border-gray-800 overflow-y-auto flex flex-col">
    <!-- Header + Create button -->
    <div class="px-5 pt-5 pb-3 flex items-start justify-between">
      <div>
        <h2 class="text-base font-semibold text-gray-100">Flow Composer</h2>
        <p class="text-xs text-gray-500 mt-0.5">Build agent workflows</p>
      </div>
      <button
        onclick={openCreatePanel}
        class="px-2.5 py-1.5 rounded-lg bg-guild-600 hover:bg-guild-500 text-xs text-white
               font-semibold transition-all duration-150 active:scale-95 shrink-0"
        title="Create new agent"
      >
        + Agent
      </button>
    </div>

    <!-- Agents palette -->
    <div class="px-4 pb-3">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Agents</h3>
      <div class="space-y-1 max-h-[200px] overflow-y-auto">
        {#each availableBlocks as block}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            draggable="true"
            ondragstart={(e) => onDragStart(e, block)}
            role="button"
            tabindex="0"
            onclick={() => addBlockFromSidebar(block)}
            onkeydown={(e) => e.key === 'Enter' && addBlockFromSidebar(block)}
            class="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-gray-800/60
                   hover:bg-gray-800 text-sm text-gray-200 cursor-grab active:cursor-grabbing
                   select-none border border-gray-700/50 hover:border-gray-600
                   transition-all duration-150 hover:shadow-md hover:shadow-black/10"
          >
            <span class="w-2 h-2 rounded-full bg-guild-400/60"></span>
            <span class="font-medium flex-1 truncate text-xs">{block.name}</span>
            <span class="text-[9px] text-gray-500 uppercase tracking-wider font-medium">{block.role || 'agent'}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- Custom blocks (composites) -->
    {#if customBlocks.length > 0}
      <div class="px-4 py-3 border-t border-gray-800">
        <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Saved Blocks</h3>
        <div class="space-y-1">
          {#each customBlocks as block, i}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="flex items-center gap-1">
              <div
                draggable="true"
                ondragstart={(e) => onDragStart(e, block)}
                role="button"
                tabindex="0"
                onclick={() => addBlockFromSidebar(block)}
                onkeydown={(e) => e.key === 'Enter' && addBlockFromSidebar(block)}
                class="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg
                       bg-purple-900/20 hover:bg-purple-900/40 text-sm text-purple-300
                       cursor-grab active:cursor-grabbing select-none
                       border border-purple-800/40 hover:border-purple-700/60 transition-all duration-150"
              >
                <span class="text-[10px]">&#9646;&#9646;</span>
                <span class="font-medium flex-1 truncate text-xs">{block.name}</span>
                <span class="text-[9px] text-purple-500">{countAgents(block.children)}x</span>
              </div>
              <button
                onclick={() => deleteCustomBlock(i)}
                class="p-1.5 rounded text-gray-600 hover:text-red-400 transition-colors"
                title="Remove block"
              >
                <span class="text-xs">&times;</span>
              </button>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Templates (REQ-V2-06) -->
    <div class="px-4 py-3 border-t border-gray-800">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Templates</h3>
      <div class="space-y-1">
        {#each builtinTemplates as template}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            draggable="true"
            ondragstart={(e) => onDragStart(e, { ...template, composite: true, nodes: template.children, edges: template.internalEdges })}
            role="button"
            tabindex="0"
            onclick={() => addBlockFromSidebar({ ...template, composite: true, nodes: template.children, edges: template.internalEdges })}
            onkeydown={(e) => e.key === 'Enter' && addBlockFromSidebar({ ...template, composite: true, nodes: template.children, edges: template.internalEdges })}
            class="flex items-center gap-2 px-3 py-2 rounded-lg
                   bg-orange-900/15 hover:bg-orange-900/30 text-sm text-orange-300 hover:text-orange-200
                   cursor-grab active:cursor-grabbing select-none
                   border border-orange-800/30 hover:border-orange-700/50 transition-all duration-150"
          >
            <span class="text-[10px]">&#9881;</span>
            <span class="font-medium flex-1 truncate text-xs">{template.name}</span>
            <span class="text-[9px] text-orange-600">{template.children.length} slots</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- Preset flows -->
    <div class="px-4 py-3 border-t border-gray-800">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Presets</h3>
      <button
        onclick={loadPresetFlow}
        class="w-full flex items-center gap-2 text-left px-3 py-2.5 rounded-lg
               bg-gradient-to-r from-guild-900/30 to-gray-800/40 hover:from-guild-900/50 hover:to-gray-800/60
               text-sm text-guild-300 hover:text-guild-200
               border border-guild-800/50 hover:border-guild-700/70 transition-all duration-150"
      >
        <span class="text-xs">&#9654;</span>
        <span class="font-medium text-xs">Full Development</span>
        <span class="ml-auto text-[9px] text-gray-500">6 agents</span>
      </button>
    </div>

    <!-- Saved flows -->
    <div class="px-4 py-3 border-t border-gray-800">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Saved Flows</h3>
      <div class="space-y-1">
        {#each teams as team}
          <button
            onclick={() => loadTeam(team)}
            class="w-full flex items-center gap-2 text-left px-3 py-2 rounded-lg
                   bg-gray-800/40 hover:bg-gray-800 text-sm text-gray-300 hover:text-white
                   border border-transparent hover:border-gray-700 transition-all duration-150"
          >
            <span class="text-[10px] text-gray-600">&#9654;</span>
            <span class="text-xs">{team.name}</span>
          </button>
        {/each}
        {#if teams.length === 0}
          <p class="text-xs text-gray-600 px-1">No saved flows yet</p>
        {/if}
      </div>
    </div>

    <!-- Spacer -->
    <div class="flex-1"></div>

    <!-- Bottom actions -->
    <div class="px-4 py-4 border-t border-gray-800 bg-gray-900/30 space-y-3">
      <!-- Save as block (multi-select) -->
      <button
        onclick={openSaveBlockPanel}
        class="w-full px-3 py-2 rounded-lg bg-purple-900/30 hover:bg-purple-900/50 text-xs text-purple-300
               hover:text-purple-200 border border-purple-800/40 hover:border-purple-700/60
               transition-all duration-150 font-medium"
      >
        Save Selection as Block
      </button>

      <!-- Save flow -->
      <div class="flex gap-2">
        <input
          type="text"
          bind:value={teamName}
          placeholder="Flow name..."
          class="flex-1 px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                 placeholder-gray-600 focus:outline-none focus:border-guild-500 focus:ring-1 focus:ring-guild-500/20
                 transition-all duration-150"
        />
        <button
          onclick={handleSave}
          class="px-4 py-2 rounded-lg bg-guild-600 hover:bg-guild-500 text-sm text-white
                 font-medium transition-all duration-150 hover:shadow-lg hover:shadow-guild-600/20
                 active:scale-95"
        >
          Save
        </button>
      </div>
      {#if saveMessage}
        <p class="text-xs px-1 {saveMessage.startsWith('Error') || saveMessage.startsWith('Select') ? 'text-red-400' : 'text-green-400'}">
          {saveMessage}
        </p>
      {/if}

      <div class="flex gap-2">
        <button
          onclick={deleteSelected}
          class="flex-1 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs text-gray-400
                 hover:text-gray-200 border border-gray-700 transition-all duration-150"
        >
          Delete Selected
        </button>
        <button
          onclick={clearCanvas}
          class="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-red-900/60 text-xs text-gray-400
                 hover:text-red-300 border border-gray-700 hover:border-red-800 transition-all duration-150"
        >
          Clear
        </button>
      </div>
    </div>
  </div>

  <!-- Canvas -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="flex-1 relative"
    ondragover={onDragOver}
    ondrop={onDrop}
  >
    {#if selectedTeam}
      <div class="absolute top-3 left-3 z-10 bg-gray-900/90 backdrop-blur-sm px-4 py-2 rounded-lg
                  text-sm text-gray-300 border border-gray-700/50 shadow-lg">
        <span class="text-gray-500">Flow:</span>
        <span class="font-semibold text-white ml-1">{selectedTeam.name}</span>
      </div>
    {/if}

    {#if nodes.length === 0}
      <div class="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
        <div class="bg-gray-900/90 backdrop-blur-sm rounded-2xl p-10 border border-gray-800 text-center shadow-2xl max-w-sm">
          <div class="text-3xl text-gray-700 mb-3">&#9830;</div>
          <p class="text-gray-300 font-medium">Build your agent workflow</p>
          <p class="text-xs text-gray-500 mt-2 leading-relaxed">
            Drag agents from the sidebar, connect them, then click to edit.
            Multi-select nodes to save as a reusable block.
          </p>
          <p class="text-xs text-guild-500 mt-3 font-medium">
            Or try "Full Development" preset &rarr;
          </p>
        </div>
      </div>
    {/if}

    <SvelteFlow
      bind:nodes
      bind:edges
      {nodeTypes}
      fitView={shouldFitView}
      onconnect={onConnect}
      onnodeclick={onNodeClick}
      onselectionchange={onSelectionChange}
      deleteKey="Backspace"
      colorMode="dark"
      selectionMode="partial"
    >
      <Controls position="bottom-right" />
      <Background gap={24} size={1} />
      <MiniMap />
    </SvelteFlow>

    <!-- Help legend -->
    <div class="absolute bottom-3 left-3 z-10">
      <button
        onclick={() => { showHelp = !showHelp; }}
        class="px-2.5 py-1.5 rounded-lg bg-gray-900/90 backdrop-blur-sm border border-gray-700/50
               text-[11px] text-gray-400 hover:text-gray-200 transition-colors shadow-lg
               {showHelp ? 'border-guild-700/50 text-guild-400' : ''}"
      >
        ? Shortcuts
      </button>
      {#if showHelp}
        <div class="mt-2 bg-gray-900/95 backdrop-blur-sm rounded-xl border border-gray-700/50 p-4 shadow-2xl w-64">
          <h4 class="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2.5">Keyboard & Mouse</h4>
          <div class="space-y-1.5 text-[11px]">
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Click</kbd>
              <span class="text-gray-400">Expand block / Edit leaf</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Shift + Drag</kbd>
              <span class="text-gray-400">Multi-select nodes</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Drag handle</kbd>
              <span class="text-gray-400">Connect ports</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Backspace</kbd>
              <span class="text-gray-400">Delete selected</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Esc</kbd>
              <span class="text-gray-400">Close panel</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Scroll</kbd>
              <span class="text-gray-400">Zoom in/out</span>
            </div>
          </div>
          <hr class="border-gray-800 my-2.5" />
          <h4 class="text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-2">Workflow</h4>
          <div class="space-y-1.5 text-[11px] text-gray-400">
            <p>1. Drag agents onto canvas (or use + Agent)</p>
            <p>2. Connect them by dragging between port handles</p>
            <p>3. Click a leaf node to edit it</p>
            <p>4. Click a <span class="text-purple-400">composite block</span> to expand inline</p>
            <p>5. <span class="text-purple-400">Shift+Drag</span> to select multiple, then "Save as Block"</p>
          </div>
        </div>
      {/if}
    </div>
  </div>

  <!-- Right panel -->
  {#if panelMode !== 'none'}
    <div class="w-80 bg-gray-900/80 backdrop-blur-sm border-l border-gray-800 flex flex-col overflow-y-auto"
         transition:fly={{ x: 320, duration: 200 }}>
      <!-- Create Agent -->
      {#if panelMode === 'create'}
        <div class="p-5 space-y-4">
          <div>
            <h3 class="text-sm font-semibold text-gray-100">Create Agent</h3>
            <p class="text-xs text-gray-500 mt-0.5">Define a new agent and add it to the canvas</p>
          </div>

          <div class="space-y-3">
            <div>
              <label for="create-name" class="text-[11px] text-gray-400 font-medium block mb-1">Name</label>
              <input id="create-name" type="text" bind:value={newAgentName} placeholder="e.g. api_designer"
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-guild-500 focus:ring-1 focus:ring-guild-500/20" />
            </div>

            <div>
              <label for="create-role" class="text-[11px] text-gray-400 font-medium block mb-1">Role</label>
              <select id="create-role" bind:value={newAgentRole}
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-guild-500">
                {#each roles as r}
                  <option value={r}>{r}</option>
                {/each}
              </select>
            </div>

            <div>
              <label for="create-model" class="text-[11px] text-gray-400 font-medium block mb-1">Model</label>
              <select id="create-model" bind:value={newAgentModel}
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-guild-500">
                {#each models as m}
                  <option value={m}>{m}</option>
                {/each}
              </select>
            </div>

            <div>
              <label for="create-instructions" class="text-[11px] text-gray-400 font-medium block mb-1">Instructions</label>
              <textarea id="create-instructions" bind:value={newAgentInstructions} rows="4"
                placeholder="What should this agent do?"
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-guild-500 focus:ring-1 focus:ring-guild-500/20
                       resize-none"></textarea>
            </div>
          </div>

          <div class="flex gap-2 pt-2">
            <button onclick={createAgent}
              class="flex-1 px-4 py-2.5 rounded-lg bg-guild-600 hover:bg-guild-500 text-sm text-white
                     font-medium transition-all duration-150 active:scale-95">
              Create & Add
            </button>
            <button onclick={() => { panelMode = 'none'; }}
              class="px-4 py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-400
                     border border-gray-700 transition-all duration-150">
              Cancel
            </button>
          </div>
        </div>
      {/if}

      <!-- Edit Agent -->
      {#if panelMode === 'edit' && selectedNode}
        <div class="p-5 space-y-4">
          <div>
            <h3 class="text-sm font-semibold text-gray-100">Edit Agent</h3>
            <p class="text-[11px] text-gray-500 mt-0.5">Node: {selectedNode.id}</p>
          </div>

          <div class="space-y-3">
            <div>
              <label for="edit-name" class="text-[11px] text-gray-400 font-medium block mb-1">Name</label>
              <input id="edit-name" type="text" bind:value={editName}
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-guild-500 focus:ring-1 focus:ring-guild-500/20" />
            </div>

            <div>
              <label for="edit-role" class="text-[11px] text-gray-400 font-medium block mb-1">Role</label>
              <select id="edit-role" bind:value={editRole}
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-guild-500">
                {#each roles as r}
                  <option value={r}>{r}</option>
                {/each}
              </select>
            </div>

            <div>
              <label for="edit-model" class="text-[11px] text-gray-400 font-medium block mb-1">Model</label>
              <select id="edit-model" bind:value={editModel}
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-guild-500">
                {#each models as m}
                  <option value={m}>{m}</option>
                {/each}
              </select>
            </div>

            <div>
              <label for="edit-instructions" class="text-[11px] text-gray-400 font-medium block mb-1">Instructions</label>
              <textarea id="edit-instructions" bind:value={editInstructions} rows="4"
                placeholder="Agent instructions..."
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-guild-500 focus:ring-1 focus:ring-guild-500/20
                       resize-none"></textarea>
            </div>
          </div>

          <!-- Port info (read-only display) -->
          {#if selectedNode.data.ports && selectedNode.data.ports.length > 0}
            <div class="bg-gray-800/60 rounded-xl p-3 border border-gray-700/50">
              <h4 class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Ports</h4>
              <div class="space-y-1">
                {#each selectedNode.data.ports as port}
                  <div class="flex items-center gap-2 text-[10px]">
                    <span class="w-1.5 h-1.5 rounded-full {port.direction === 'input' ? 'bg-green-400' : 'bg-blue-400'}"></span>
                    <span class="text-gray-300">{port.name}</span>
                    <span class="text-gray-600 ml-auto">{port.type_tag}</span>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <div class="flex gap-2 pt-2">
            <button onclick={applyEdit}
              class="flex-1 px-4 py-2.5 rounded-lg bg-guild-600 hover:bg-guild-500 text-sm text-white
                     font-medium transition-all duration-150 active:scale-95">
              Apply
            </button>
            <button onclick={deleteNode}
              class="px-4 py-2.5 rounded-lg bg-red-900/50 hover:bg-red-900/80 text-sm text-red-300
                     border border-red-800/50 transition-all duration-150">
              Delete
            </button>
            <button onclick={() => { panelMode = 'none'; selectedNode = null; }}
              class="px-4 py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-400
                     border border-gray-700 transition-all duration-150">
              Close
            </button>
          </div>
        </div>
      {/if}

      <!-- Save as Block -->
      {#if panelMode === 'save-block'}
        <div class="p-5 space-y-4">
          <div>
            <h3 class="text-sm font-semibold text-gray-100">Save as Block</h3>
            <p class="text-xs text-gray-500 mt-0.5">
              Package {getSelectedNodes().length} selected agents as a reusable block
            </p>
          </div>

          <div class="bg-purple-900/20 rounded-lg p-3 border border-purple-800/30">
            <p class="text-[11px] text-purple-300 font-medium mb-1">Included agents:</p>
            <div class="flex flex-wrap gap-1">
              {#each getSelectedNodes() as node}
                <span class="px-2 py-0.5 rounded bg-purple-900/40 text-[10px] text-purple-200 border border-purple-800/40">
                  {node.data.blockName}
                </span>
              {/each}
            </div>
          </div>

          <div class="space-y-3">
            <div>
              <label for="block-name" class="text-[11px] text-gray-400 font-medium block mb-1">Block name</label>
              <input id="block-name" type="text" bind:value={blockName} placeholder="e.g. review-pipeline"
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20" />
            </div>

            <div>
              <label for="block-desc" class="text-[11px] text-gray-400 font-medium block mb-1">Description</label>
              <input id="block-desc" type="text" bind:value={blockDescription} placeholder="What does this block do?"
                class="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20" />
            </div>
          </div>

          <div class="flex gap-2 pt-2">
            <button onclick={saveAsBlock}
              class="flex-1 px-4 py-2.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-sm text-white
                     font-medium transition-all duration-150 active:scale-95">
              Save Block
            </button>
            <button onclick={() => { panelMode = 'none'; }}
              class="px-4 py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-400
                     border border-gray-700 transition-all duration-150">
              Cancel
            </button>
          </div>
        </div>
      {/if}

    </div>
  {/if}
</div>

<style>
  :global(.svelte-flow) {
    background: #0a0f1a !important;
  }
  :global(.svelte-flow__minimap) {
    background: rgb(17 24 39 / 0.9) !important;
    border: 1px solid rgb(55 65 81 / 0.5) !important;
    border-radius: 0.75rem !important;
  }
  :global(.svelte-flow__controls) {
    background: rgb(17 24 39 / 0.9) !important;
    border: 1px solid rgb(55 65 81 / 0.5) !important;
    border-radius: 0.75rem !important;
    overflow: hidden;
  }
  :global(.svelte-flow__controls button) {
    background: transparent !important;
    border-bottom-color: rgb(55 65 81 / 0.3) !important;
    color: #9ca3af !important;
    fill: #9ca3af !important;
  }
  :global(.svelte-flow__controls button:hover) {
    background: rgb(55 65 81 / 0.3) !important;
  }
  :global(.svelte-flow__controls button svg) {
    fill: #9ca3af !important;
  }
  :global(.svelte-flow__edge-path) {
    stroke: #38bdf8 !important;
    stroke-width: 2px !important;
  }
  :global(.svelte-flow__attribution) {
    display: none !important;
  }
  :global(.svelte-flow__selection) {
    background: rgba(147, 51, 234, 0.08) !important;
    border: 1px solid rgba(147, 51, 234, 0.4) !important;
    border-radius: 0.5rem !important;
  }
</style>
