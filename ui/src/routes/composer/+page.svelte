<script>
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { fetchBlocks, fetchTeams, saveTeam } from '$lib/api.js';
  import BlockNode from '$lib/components/BlockNode.svelte';

  // --- Core flow state ---
  let nodes = $state([]);
  let edges = $state([]);
  let shouldFitView = $state(false);

  // --- Sidebar data ---
  let availableBlocks = $state([]);
  let customBlocks = $state([]);
  let teams = $state([]);
  let selectedTeam = $state(null);
  let teamName = $state('');
  let saveMessage = $state('');
  let draggedBlock = $state(null);

  // --- Right panel state ---
  let panelMode = $state('none'); // 'none' | 'create' | 'edit' | 'save-block'
  let selectedNode = $state(null);
  let showHelp = $state(false);
  let selectedNodeIds = $state(new Set());

  // --- Create agent form ---
  let newAgentName = $state('');
  let newAgentRole = $state('agent');
  let newAgentModel = $state('gemma4-4b-dense-med');
  let newAgentInstructions = $state('');

  // --- Edit agent form ---
  let editName = $state('');
  let editRole = $state('');
  let editModel = $state('');
  let editInstructions = $state('');
  let editVerifier = $state('');
  let editLoopUntil = $state('');
  let editMaxIterations = $state(5);

  // --- Save as block form ---
  let blockName = $state('');
  let blockDescription = $state('');

  // --- Block expand/collapse state ---
  // Maps blockNodeId -> { originalNode, childNodeIds, internalEdgeIds, hiddenEdgeIds }
  let expandedBlocks = $state(new Map());

  const nodeTypes = { block: BlockNode };

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

  onMount(async () => {
    availableBlocks = await fetchBlocks();
    teams = await fetchTeams();
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
    const isComposite = !!(block.composite && block.nodes && block.nodes.length > 0);

    const newNode = {
      id,
      type: 'block',
      position,
      data: {
        blockName: block.name,
        role: block.role || 'agent',
        model: block.model || 'gemma4-4b-dense-med',
        instructions: block.instructions || '',
        verifier: null,
        loopUntil: null,
        maxIterations: null,
        // Composite block metadata (stored but not rendered in node)
        isComposite,
        agentCount: isComposite ? block.nodes.length : 0,
        // Store full child data for expansion
        _childNodes: isComposite ? block.nodes : null,
        _childEdges: isComposite ? (block.edges || []) : null,
      },
    };
    nodes = [...nodes, newNode];
  }

  function addBlockFromSidebar(block) {
    const col = nodes.length % 4;
    const row = Math.floor(nodes.length / 4);
    placeBlockOnCanvas(block, { x: 80 + col * 240, y: 80 + row * 180 });
  }

  // ===== Block Expand / Collapse (REQ-UI-04.4 - 04.7) =====

  // Layout constants for expanded containers
  const CONTAINER_PADDING_X = 30;
  const CONTAINER_PADDING_TOP = 50; // space for header
  const CONTAINER_PADDING_BOTTOM = 30;
  const CHILD_SPACING_X = 220;
  const CHILD_SPACING_Y = 140;
  const CHILD_COLS = 3;

  function expandBlock(blockNode) {
    const blockId = blockNode.id;
    const childNodesData = blockNode.data._childNodes || [];
    const childEdgesData = blockNode.data._childEdges || [];

    // Build ID mapping: original child id -> new canvas id
    const idMap = {};
    const childNodeIds = [];

    // Calculate child positions relative to parent (container-local coords)
    const newChildNodes = childNodesData.map((child, index) => {
      const origId = child.id || child.data?.blockName || `child-${Math.random().toString(36).slice(2, 6)}`;
      const canvasId = `${blockId}__${origId}`;
      idMap[origId] = canvasId;
      const childBlockName = child.data?.blockName || child.blockName;
      if (childBlockName && childBlockName !== origId) {
        idMap[childBlockName] = canvasId;
      }
      childNodeIds.push(canvasId);

      const childData = child.data || {};
      const isChildComposite = !!(childData.isComposite || (childData._childNodes && childData._childNodes.length > 0));

      // Position relative to parent: use stored position or auto-layout grid
      const col = index % CHILD_COLS;
      const row = Math.floor(index / CHILD_COLS);
      const relX = child.position?.x != null ? child.position.x + CONTAINER_PADDING_X : CONTAINER_PADDING_X + col * CHILD_SPACING_X;
      const relY = child.position?.y != null ? child.position.y + CONTAINER_PADDING_TOP : CONTAINER_PADDING_TOP + row * CHILD_SPACING_Y;

      return {
        id: canvasId,
        type: 'block',
        position: { x: relX, y: relY },
        parentId: blockId,
        extent: 'parent',
        data: {
          blockName: childData.blockName || child.blockName || 'agent',
          role: childData.role || child.role || 'agent',
          model: childData.model || child.model || 'gemma4-4b-dense-med',
          instructions: childData.instructions || child.instructions || '',
          verifier: childData.verifier || null,
          loopUntil: childData.loopUntil || null,
          maxIterations: childData.maxIterations || null,
          isComposite: isChildComposite,
          agentCount: isChildComposite ? (childData._childNodes || childData.nodes || []).length : 0,
          _childNodes: childData._childNodes || (child.composite ? child.nodes : null) || null,
          _childEdges: childData._childEdges || (child.composite ? child.edges : null) || null,
          _parentBlockId: blockId,
        },
      };
    });

    // Calculate container size to fit all children (wider for composites which render larger)
    let maxX = 0;
    let maxY = 0;
    for (const child of newChildNodes) {
      const childWidth = child.data.isComposite ? 220 : 200;
      const childHeight = child.data.isComposite ? 80 : 70;
      maxX = Math.max(maxX, child.position.x + childWidth);
      maxY = Math.max(maxY, child.position.y + childHeight);
    }
    const containerWidth = Math.max(maxX + CONTAINER_PADDING_X, 320);
    const containerHeight = Math.max(maxY + CONTAINER_PADDING_BOTTOM, 180);

    // Create internal edges with dashed purple styling
    const internalEdgeIds = [];
    const newInternalEdges = childEdgesData.map((edge) => {
      const edgeId = `${blockId}__edge__${edge.id || edge.source + '-' + edge.target}`;
      internalEdgeIds.push(edgeId);
      const resolvedSource = idMap[edge.source] || edge.source;
      const resolvedTarget = idMap[edge.target] || edge.target;
      return {
        id: edgeId,
        source: resolvedSource,
        target: resolvedTarget,
        animated: true,
        style: 'stroke: #a78bfa; stroke-width: 2px; stroke-dasharray: 5 3; opacity: 0.7;',
      };
    });

    // Store expansion state (save original node data for collapse restore)
    const newExpandedBlocks = new Map(expandedBlocks);
    newExpandedBlocks.set(blockId, {
      originalData: { ...blockNode.data },
      originalStyle: blockNode.style || undefined,
      childNodeIds,
      internalEdgeIds,
    });
    expandedBlocks = newExpandedBlocks;

    // Mutate the block node in-place: expand it into a container
    nodes = [
      ...nodes.map((n) => {
        if (n.id === blockId) {
          return {
            ...n,
            style: `width: ${containerWidth}px; height: ${containerHeight}px;`,
            data: {
              ...n.data,
              expanded: true,
              onCollapse: () => collapseBlock(blockId),
              onUngroup: () => ungroupBlock(blockId),
            },
          };
        }
        return n;
      }),
      ...newChildNodes,
    ];
    edges = [...edges, ...newInternalEdges];
  }

  function collapseBlock(blockId) {
    const state = expandedBlocks.get(blockId);
    if (!state) return;

    const { originalData, originalStyle, childNodeIds, internalEdgeIds } = state;
    const childIdSet = new Set(childNodeIds);
    const internalEdgeIdSet = new Set(internalEdgeIds);

    // Recursively collapse any expanded child blocks first
    for (const childId of childNodeIds) {
      if (expandedBlocks.has(childId)) {
        collapseBlock(childId);
      }
    }

    // Remove child nodes, remove internal edges, restore block node to compact form
    nodes = nodes
      .filter((n) => !childIdSet.has(n.id))
      .map((n) => {
        if (n.id === blockId) {
          return {
            ...n,
            style: originalStyle || undefined,
            data: {
              ...originalData,
            },
          };
        }
        return n;
      });
    edges = edges.filter((e) => !internalEdgeIdSet.has(e.id));

    // Remove from expanded map
    const newExpandedBlocks = new Map(expandedBlocks);
    newExpandedBlocks.delete(blockId);
    expandedBlocks = newExpandedBlocks;
  }

  function ungroupBlock(blockId) {
    const state = expandedBlocks.get(blockId);
    if (!state) return;

    const { childNodeIds, internalEdgeIds } = state;
    const internalEdgeIdSet = new Set(internalEdgeIds);

    // Find the parent block node to get its absolute position
    const parentNode = nodes.find((n) => n.id === blockId);
    if (!parentNode) return;
    const parentX = parentNode.position.x;
    const parentY = parentNode.position.y;

    // Recursively collapse any expanded nested blocks first
    for (const childId of childNodeIds) {
      if (expandedBlocks.has(childId)) {
        collapseBlock(childId);
      }
    }

    // Convert child nodes: remove parentId, convert relative positions to absolute
    // Remove the parent block node entirely
    // Convert internal edges to regular edges
    nodes = nodes
      .filter((n) => n.id !== blockId)
      .map((n) => {
        if (n.parentId === blockId) {
          return {
            ...n,
            parentId: undefined,
            extent: undefined,
            position: {
              x: parentX + n.position.x,
              y: parentY + n.position.y,
            },
            data: {
              ...n.data,
              _parentBlockId: undefined,
            },
          };
        }
        return n;
      });

    // Convert internal purple dashed edges to regular blue edges
    edges = edges.map((e) => {
      if (internalEdgeIdSet.has(e.id)) {
        return {
          ...e,
          style: 'stroke: #38bdf8; stroke-width: 2px;',
        };
      }
      return e;
    });

    // Re-route any edges that connected to the block node to connect to the first/last child
    // (For simplicity, edges TO the block -> first child, edges FROM the block -> last child)
    const firstChild = childNodeIds[0];
    const lastChild = childNodeIds[childNodeIds.length - 1];
    if (firstChild || lastChild) {
      edges = edges.map((e) => {
        if (e.target === blockId && firstChild) {
          return { ...e, target: firstChild };
        }
        if (e.source === blockId && lastChild) {
          return { ...e, source: lastChild };
        }
        return e;
      });
    }

    // Remove from expanded map
    const newExpandedBlocks = new Map(expandedBlocks);
    newExpandedBlocks.delete(blockId);
    expandedBlocks = newExpandedBlocks;
  }

  // ===== Node Click Handler =====

  function onNodeClick({ node }) {
    if (!node || node.type !== 'block') return;

    if (node.data.isComposite) {
      const blockId = node.id;
      // If already expanded, collapse it (toggle behavior)
      if (expandedBlocks.has(blockId)) {
        collapseBlock(blockId);
        return;
      }
      // Prevent expanding if this node is a child of another expanded block
      // (xyflow doesn't support nested parentId)
      if (node.data._parentBlockId) {
        selectedNode = node;
        panelMode = 'edit';
        editName = node.data.blockName || '';
        editRole = node.data.role || 'agent';
        editModel = node.data.model || 'gemma4-4b-dense-med';
        editInstructions = node.data.instructions || '';
        editVerifier = node.data.verifier || '';
        editLoopUntil = node.data.loopUntil || '';
        editMaxIterations = node.data.maxIterations || 5;
        return;
      }
      expandBlock(node);
      return;
    }

    // Regular node: open edit panel
    selectedNode = node;
    editName = node.data.blockName || '';
    editRole = node.data.role || 'agent';
    editModel = node.data.model || 'gemma4-4b-dense-med';
    editInstructions = node.data.instructions || '';
    editVerifier = node.data.verifier || '';
    editLoopUntil = node.data.loopUntil || '';
    editMaxIterations = node.data.maxIterations || 5;
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
    nodes = nodes.map((n) => {
      if (n.id === selectedNode.id) {
        return {
          ...n,
          data: {
            ...n.data,
            blockName: editName,
            role: editRole,
            model: editModel,
            instructions: editInstructions,
            verifier: editVerifier || null,
            loopUntil: editLoopUntil || null,
            maxIterations: editMaxIterations || null,
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
    // If the node is an expanded block, collapse it first to clean up children
    if (expandedBlocks.has(nodeId)) {
      collapseBlock(nodeId);
    }
    edges = edges.filter((e) => e.source !== nodeId && e.target !== nodeId);
    nodes = nodes.filter((n) => n.id !== nodeId);
    panelMode = 'none';
    selectedNode = null;
  }

  // ===== Save as Block (REQ-UI-04.2) =====

  function getSelectedNodes() {
    return nodes.filter((n) => selectedNodeIds.has(n.id));
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

    // Normalize positions relative to the top-left of the selection
    const minX = Math.min(...selected.map((n) => n.position.x));
    const minY = Math.min(...selected.map((n) => n.position.y));

    // Use blockName as stable identifier for edges (not canvas IDs which are ephemeral)
    // Handle duplicates by appending index suffix
    const idToBlockName = {};
    const usedNames = {};
    for (const n of selected) {
      let name = n.data.blockName || n.id;
      if (usedNames[name]) {
        name = `${name}_${usedNames[name]}`;
      }
      usedNames[n.data.blockName || n.id] = (usedNames[n.data.blockName || n.id] || 0) + 1;
      idToBlockName[n.id] = name;
    }

    const blockNodes = selected.map((n) => {
      // Clean copy of data: remove stale callbacks, keep structural info
      const cleanData = { ...n.data };
      delete cleanData.onCollapse;
      delete cleanData.onUngroup;
      delete cleanData.expanded;
      delete cleanData._parentBlockId;
      return {
        id: idToBlockName[n.id],
        position: { x: n.position.x - minX, y: n.position.y - minY },
        data: cleanData,
      };
    });

    // Capture internal edges mapped to stable blockName identifiers
    const selectedIds = new Set(selected.map((n) => n.id));
    const blockEdges = edges
      .filter((e) => selectedIds.has(e.source) && selectedIds.has(e.target))
      .map((e) => ({ id: `${idToBlockName[e.source]}-${idToBlockName[e.target]}`, source: idToBlockName[e.source], target: idToBlockName[e.target] }));

    // Count total agents recursively (composite children count their internal agents)
    function countAgents(nodeList) {
      let total = 0;
      for (const n of nodeList) {
        if (n.data?.isComposite && n.data?._childNodes) {
          total += countAgents(n.data._childNodes);
        } else {
          total += 1;
        }
      }
      return total;
    }

    const compositeBlock = {
      name: blockName.trim(),
      role: 'orchestrator',
      description: blockDescription || `Composite: ${selected.map((n) => n.data.blockName).join(' + ')}`,
      composite: true,
      nodes: blockNodes,
      edges: blockEdges,
      agentCount: countAgents(blockNodes),
    };

    customBlocks = [...customBlocks, compositeBlock];
    persistCustomBlocks();
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
    // Collapse any expanded blocks that are being deleted
    for (const nodeId of selectedNodeIds) {
      if (expandedBlocks.has(nodeId)) {
        collapseBlock(nodeId);
      }
    }
    edges = edges.filter((e) => !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target));
    nodes = nodes.filter((n) => !selectedNodeIds.has(n.id));
    selectedNodeIds = new Set();
  }

  // ===== Preset Flow (REQ-UI-05) =====

  function loadPresetFlow() {
    nodes = [
      { id: 'req', type: 'block', position: { x: 50, y: 150 }, data: { blockName: 'requirements', role: 'planner', model: 'gemma4-4b-dense-med', instructions: builtinRoles[0].instructions, verifier: 'requirements_verifier', loopUntil: 'verifier approves', maxIterations: 5, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
      { id: 'arch', type: 'block', position: { x: 300, y: 150 }, data: { blockName: 'architect', role: 'architect', model: 'gemma4-4b-dense-med', instructions: builtinRoles[1].instructions, verifier: 'architect_verifier', loopUntil: 'verifier approves', maxIterations: 5, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
      { id: 'tester', type: 'block', position: { x: 550, y: 100 }, data: { blockName: 'tester', role: 'tester', model: 'gemma4-4b-dense-med', instructions: builtinRoles[3].instructions, verifier: 'tester_verifier', loopUntil: 'verifier approves', maxIterations: 5, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
      { id: 'impl', type: 'block', position: { x: 550, y: 200 }, data: { blockName: 'implementer', role: 'implementer', model: 'gemma4-4b-dense-med', instructions: builtinRoles[2].instructions, verifier: 'test_runner', loopUntil: 'tests pass', maxIterations: 5, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
      { id: 'review', type: 'block', position: { x: 800, y: 150 }, data: { blockName: 'code_reviewer', role: 'reviewer', model: 'gemma4-26b-moe-agent', instructions: builtinRoles[5].instructions, verifier: null, loopUntil: 'reviewer approves', maxIterations: 3, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
      { id: 'verif', type: 'block', position: { x: 1050, y: 150 }, data: { blockName: 'verificator', role: 'verifier', model: 'gemma4-26b-moe-agent', instructions: builtinRoles[6].instructions, verifier: null, loopUntil: 'all checks pass', maxIterations: null, isComposite: false, agentCount: 0, _childNodes: null, _childEdges: null } },
    ];
    edges = [
      { id: 'e-req-arch', source: 'req', target: 'arch', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-tester', source: 'arch', target: 'tester', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-impl', source: 'arch', target: 'impl', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-tester-review', source: 'tester', target: 'review', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-impl-review', source: 'impl', target: 'review', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-review-verif', source: 'review', target: 'verif', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
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
      teamNodes.push({
        id: instance,
        type: 'block',
        position,
        data: {
          blockName: isObj ? blockType.name || instance : instance,
          role,
          model: (isObj && blockType.model) || 'gemma4-4b-dense-med',
          instructions: (isObj && blockType.instructions) || '',
          verifier: (isObj && blockType.verifier) || null,
          loopUntil: (isObj && blockType.loopUntil) || null,
          maxIterations: (isObj && blockType.maxIterations) || null,
          isComposite: false,
          agentCount: 0,
          _childNodes: null,
          _childEdges: null,
        },
      });
      if (!isObj || !blockType.position) x += 250;
    }
    for (const conn of team.connections || []) {
      teamEdges.push({
        id: `${conn.source_block}-${conn.target_block}`,
        source: conn.source_block,
        target: conn.target_block,
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
      await saveTeam(teamName.trim(), nodes, edges);
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
                <span class="text-[9px] text-purple-500">{block.agentCount}x</span>
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
              <span class="text-gray-400">Select & edit node</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Shift + Drag</kbd>
              <span class="text-gray-400">Multi-select nodes</span>
            </div>
            <div class="flex items-center gap-3">
              <kbd class="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-300 font-mono">Drag handle</kbd>
              <span class="text-gray-400">Connect two agents</span>
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
            <p>2. Connect them by dragging between handles</p>
            <p>3. Click a node to edit or attach a verifier</p>
            <p>4. <span class="text-purple-400">Shift+Drag</span> to select multiple, then "Save as Block"</p>
            <p>5. Click a <span class="text-purple-400">block</span> to expand/collapse inline</p>
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

          <!-- Verifier section -->
          <div class="bg-gray-800/60 rounded-xl p-4 border border-gray-700/50 space-y-3">
            <h4 class="text-[11px] font-semibold text-orange-400 uppercase tracking-wider flex items-center gap-1.5">
              <span>&#8635;</span> Verification Loop
            </h4>

            <div>
              <label for="edit-verifier" class="text-[11px] text-gray-400 font-medium block mb-1">Verifier agent</label>
              <input id="edit-verifier" type="text" bind:value={editVerifier}
                placeholder="e.g. requirements_verifier"
                class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20" />
            </div>

            <div>
              <label for="edit-loop" class="text-[11px] text-gray-400 font-medium block mb-1">Loop until</label>
              <input id="edit-loop" type="text" bind:value={editLoopUntil}
                placeholder="e.g. verifier approves"
                class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                       placeholder-gray-600 focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20" />
            </div>

            <div>
              <label for="edit-max-iter" class="text-[11px] text-gray-400 font-medium block mb-1">Max iterations</label>
              <input id="edit-max-iter" type="number" bind:value={editMaxIterations} min="1" max="20"
                class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                       focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20" />
            </div>
          </div>

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
