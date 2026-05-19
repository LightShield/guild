<script>
  import { onMount } from 'svelte';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { fetchBlocks, fetchTeams, saveTeam } from '$lib/api.js';
  import BlockNode from '$lib/components/BlockNode.svelte';
  import PhaseNode from '$lib/components/PhaseNode.svelte';

  let nodes = $state([]);
  let edges = $state([]);
  let availableBlocks = $state([]);
  let teams = $state([]);
  let selectedTeam = $state(null);
  let teamName = $state('');
  let saveMessage = $state('');
  let draggedBlock = $state(null);
  let selectedNode = $state(null);
  let verifierName = $state('');
  let loopCondition = $state('');
  let maxIterations = $state(5);
  let showNodeConfig = $state(false);

  const nodeTypes = { block: BlockNode, phase: PhaseNode };

  const builtinRoles = [
    { name: 'requirements', role: 'planner', description: 'Gather and document requirements' },
    { name: 'architect', role: 'architect', description: 'Design system architecture' },
    { name: 'implementer', role: 'implementer', description: 'Write implementation code' },
    { name: 'tester', role: 'tester', description: 'Write tests (TDD)' },
    { name: 'test_runner', role: 'tester', description: 'Execute test suites' },
    { name: 'code_reviewer', role: 'reviewer', description: 'Review code quality' },
    { name: 'verificator', role: 'verifier', description: 'Final verification gate' },
  ];

  onMount(async () => {
    availableBlocks = await fetchBlocks();
    teams = await fetchTeams();
    if (availableBlocks.length === 0) {
      availableBlocks = builtinRoles;
    }
  });

  // --- Drag and drop from palette ---

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
      try {
        block = JSON.parse(event.dataTransfer.getData('application/guild-block'));
      } catch {
        return;
      }
    }

    const flowContainer = event.currentTarget;
    const bounds = flowContainer.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;

    createBlockNode(block, { x, y });
    draggedBlock = null;
  }

  function createBlockNode(block, position) {
    const id = `${block.name}-${Date.now()}-${nodes.length}`;
    const newNode = {
      id,
      type: 'block',
      position,
      data: {
        label: `${block.name} (${block.role || 'agent'})`,
        blockName: block.name,
        role: block.role || 'agent',
        verifier: null,
        loopUntil: null,
        maxIterations: null,
      },
    };
    nodes = [...nodes, newNode];
  }

  function addBlock(block) {
    const position = {
      x: 100 + nodes.length * 220,
      y: 150 + (nodes.length % 3) * 150,
    };
    createBlockNode(block, position);
  }

  // --- Connection drawing ---

  function onConnect(connection) {
    const edgeId = `e-${connection.source}-${connection.target}-${edges.length}`;
    const newEdge = {
      id: edgeId,
      source: connection.source,
      target: connection.target,
      sourceHandle: connection.sourceHandle,
      targetHandle: connection.targetHandle,
      animated: true,
      style: 'stroke: #38bdf8; stroke-width: 2px;',
      labelStyle: 'fill: #94a3b8; font-size: 11px;',
    };
    edges = [...edges, newEdge];
  }

  // --- Node selection ---

  function onNodeClick(event) {
    const node = event.detail?.node || event.node;
    if (node && node.type === 'block') {
      selectedNode = node;
      verifierName = node.data.verifier || '';
      loopCondition = node.data.loopUntil || '';
      maxIterations = node.data.maxIterations || 5;
      showNodeConfig = true;
    }
  }

  function applyVerifier() {
    if (!selectedNode) return;
    nodes = nodes.map(n => {
      if (n.id === selectedNode.id) {
        return {
          ...n,
          data: {
            ...n.data,
            verifier: verifierName || null,
            loopUntil: loopCondition || null,
            maxIterations: maxIterations || null,
          }
        };
      }
      return n;
    });
    showNodeConfig = false;
    selectedNode = null;
  }

  function removeVerifier() {
    if (!selectedNode) return;
    nodes = nodes.map(n => {
      if (n.id === selectedNode.id) {
        return {
          ...n,
          data: { ...n.data, verifier: null, loopUntil: null, maxIterations: null }
        };
      }
      return n;
    });
    verifierName = '';
    loopCondition = '';
    showNodeConfig = false;
    selectedNode = null;
  }

  // --- Delete selected nodes/edges ---

  function onKeyDown(event) {
    if (event.key === 'Backspace' || event.key === 'Delete') {
      deleteSelected();
    }
    if (event.key === 'Escape') {
      showNodeConfig = false;
      selectedNode = null;
    }
  }

  function deleteSelected() {
    const selectedNodeIds = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
    const selectedEdgeIds = new Set(edges.filter((e) => e.selected).map((e) => e.id));

    if (selectedNodeIds.size === 0 && selectedEdgeIds.size === 0) return;

    edges = edges.filter(
      (e) => !selectedEdgeIds.has(e.id) && !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target)
    );
    nodes = nodes.filter((n) => !selectedNodeIds.has(n.id));
  }

  // --- Load preset flow ---

  function loadPresetFlow() {
    const presetNodes = [
      { id: 'req', type: 'block', position: { x: 50, y: 150 }, data: { blockName: 'requirements', role: 'planner', verifier: 'requirements_verifier', loopUntil: 'verifier approves', maxIterations: 5 } },
      { id: 'arch', type: 'block', position: { x: 300, y: 150 }, data: { blockName: 'architect', role: 'architect', verifier: 'architect_verifier', loopUntil: 'verifier approves', maxIterations: 5 } },
      { id: 'tester', type: 'block', position: { x: 550, y: 80 }, data: { blockName: 'tester', role: 'tester', verifier: 'tester_verifier', loopUntil: 'verifier approves', maxIterations: 5 } },
      { id: 'impl', type: 'block', position: { x: 550, y: 250 }, data: { blockName: 'implementer', role: 'implementer', verifier: 'test_runner', loopUntil: 'tests pass', maxIterations: 5 } },
      { id: 'review', type: 'block', position: { x: 800, y: 150 }, data: { blockName: 'code_reviewer', role: 'reviewer', verifier: null, loopUntil: 'reviewer approves', maxIterations: 3 } },
      { id: 'verif', type: 'block', position: { x: 1050, y: 150 }, data: { blockName: 'verificator', role: 'verifier', verifier: null, loopUntil: 'all checks pass', maxIterations: null } },
    ];

    const presetEdges = [
      { id: 'e-req-arch', source: 'req', target: 'arch', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-tester', source: 'arch', target: 'tester', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-arch-impl', source: 'arch', target: 'impl', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-tester-review', source: 'tester', target: 'review', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-impl-review', source: 'impl', target: 'review', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
      { id: 'e-review-verif', source: 'review', target: 'verif', animated: true, style: 'stroke: #38bdf8; stroke-width: 2px;' },
    ];

    nodes = presetNodes;
    edges = presetEdges;
    teamName = 'full-development';
    selectedTeam = { name: 'full-development' };
  }

  // --- Load team ---

  function loadTeam(team) {
    selectedTeam = team;
    teamName = team.name;
    const teamNodes = [];
    const teamEdges = [];
    let x = 50;

    const blockEntries = Object.entries(team.blocks || {});
    for (const [instance, blockType] of blockEntries) {
      const role = typeof blockType === 'object' ? blockType.role || 'agent' : 'agent';
      const name = typeof blockType === 'string' ? blockType : blockType.name || instance;
      teamNodes.push({
        id: instance,
        type: 'block',
        position: { x, y: 150 + (teamNodes.length % 3) * 150 },
        data: {
          blockName: instance,
          role,
          verifier: null,
          loopUntil: null,
          maxIterations: null,
        },
      });
      x += 250;
    }

    for (const conn of team.connections || []) {
      teamEdges.push({
        id: `${conn.source_block}-${conn.target_block}`,
        source: conn.source_block,
        target: conn.target_block,
        label: `${conn.source_port} -> ${conn.target_port}`,
        animated: true,
        style: 'stroke: #38bdf8; stroke-width: 2px;',
        labelStyle: 'fill: #94a3b8; font-size: 11px;',
      });
    }

    nodes = teamNodes;
    edges = teamEdges;
  }

  // --- Save team ---

  async function handleSave() {
    if (!teamName.trim()) {
      saveMessage = 'Please enter a team name.';
      return;
    }

    try {
      await saveTeam(teamName.trim(), nodes, edges);
      saveMessage = `Saved "${teamName}"`;
      teams = await fetchTeams();
      setTimeout(() => (saveMessage = ''), 3000);
    } catch (e) {
      saveMessage = `Error: ${e.message}`;
    }
  }

  // --- Clear ---

  function clearCanvas() {
    nodes = [];
    edges = [];
    selectedTeam = null;
    teamName = '';
    saveMessage = '';
    showNodeConfig = false;
    selectedNode = null;
  }
</script>

<svelte:head>
  <title>Guild - Flow Composer</title>
</svelte:head>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="h-[calc(100vh-4rem)] flex" onkeydown={onKeyDown}>
  <!-- Left sidebar: block palette -->
  <div class="w-72 bg-gray-900/50 border-r border-gray-800 overflow-y-auto flex flex-col">
    <!-- Header -->
    <div class="px-5 pt-5 pb-3">
      <h2 class="text-base font-semibold text-gray-100">Flow Composer</h2>
      <p class="text-xs text-gray-500 mt-0.5">Build agent workflows with verification loops</p>
    </div>

    <!-- Agents palette -->
    <div class="px-4 pb-3">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Agents</h3>
      <div class="space-y-1">
        {#each availableBlocks as block}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            draggable="true"
            ondragstart={(e) => onDragStart(e, block)}
            role="button"
            tabindex="0"
            onclick={() => addBlock(block)}
            onkeydown={(e) => e.key === 'Enter' && addBlock(block)}
            class="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-gray-800/60
                   hover:bg-gray-800 text-sm text-gray-200 cursor-grab active:cursor-grabbing
                   select-none border border-gray-700/50 hover:border-gray-600
                   transition-all duration-150 hover:shadow-md hover:shadow-black/10"
          >
            <span class="w-2 h-2 rounded-full bg-guild-400/60"></span>
            <span class="font-medium flex-1 truncate">{block.name}</span>
            <span class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">{block.role || 'agent'}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- Preset flows -->
    <div class="px-4 py-3 border-t border-gray-800">
      <h3 class="text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-1 mb-2">Preset Flows</h3>
      <button
        onclick={loadPresetFlow}
        class="w-full flex items-center gap-2 text-left px-3 py-2.5 rounded-lg
               bg-gradient-to-r from-guild-900/30 to-gray-800/40 hover:from-guild-900/50 hover:to-gray-800/60
               text-sm text-guild-300 hover:text-guild-200
               border border-guild-800/50 hover:border-guild-700/70 transition-all duration-150"
      >
        <span class="text-xs">&#9654;</span>
        <span class="font-medium">Full Development</span>
        <span class="ml-auto text-[9px] text-gray-500">6 agents</span>
      </button>
    </div>

    <!-- Saved teams -->
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
            {team.name}
          </button>
        {/each}
        {#if teams.length === 0}
          <p class="text-xs text-gray-600 px-1">No saved flows yet</p>
        {/if}
      </div>
    </div>

    <!-- Spacer -->
    <div class="flex-1"></div>

    <!-- Save section -->
    <div class="px-4 py-4 border-t border-gray-800 bg-gray-900/30">
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
        <p class="text-xs mt-2 px-1 {saveMessage.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">
          {saveMessage}
        </p>
      {/if}

      <!-- Actions -->
      <div class="flex gap-2 mt-3">
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

  <!-- Canvas: flow editor -->
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
            Drag agents from the sidebar, connect them with edges,
            then click a node to attach a verifier loop.
          </p>
          <p class="text-xs text-guild-500 mt-3 font-medium">
            Or try the "Full Development" preset &rarr;
          </p>
        </div>
      </div>
    {/if}

    <SvelteFlow
      {nodes}
      {edges}
      {nodeTypes}
      fitView
      onconnect={onConnect}
      onnodeclick={onNodeClick}
      deleteKey="Backspace"
      colorMode="dark"
    >
      <Controls position="bottom-right" />
      <Background gap={24} size={1} />
      <MiniMap />
    </SvelteFlow>
  </div>

  <!-- Right panel: node config (verifier decorator) -->
  {#if showNodeConfig && selectedNode}
    <div class="w-72 bg-gray-900/80 backdrop-blur-sm border-l border-gray-800 p-5 flex flex-col gap-4 overflow-y-auto">
      <div>
        <h3 class="text-sm font-semibold text-gray-100">Configure Agent</h3>
        <p class="text-xs text-gray-500 mt-0.5">{selectedNode.data.blockName}</p>
      </div>

      <div class="bg-gray-800/60 rounded-xl p-4 border border-gray-700/50 space-y-3">
        <h4 class="text-[11px] font-semibold text-orange-400 uppercase tracking-wider flex items-center gap-1.5">
          <span>&#8635;</span> Verifier Decorator
        </h4>
        <p class="text-[11px] text-gray-500 leading-relaxed">
          Attach a verifier that loops this agent until a condition is met.
        </p>

        <div>
          <label for="verifier-name" class="text-[11px] text-gray-400 font-medium block mb-1">Verifier agent</label>
          <input
            id="verifier-name"
            type="text"
            bind:value={verifierName}
            placeholder="e.g. requirements_verifier"
            class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                   placeholder-gray-600 focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20"
          />
        </div>

        <div>
          <label for="loop-condition" class="text-[11px] text-gray-400 font-medium block mb-1">Loop until</label>
          <input
            id="loop-condition"
            type="text"
            bind:value={loopCondition}
            placeholder="e.g. verifier approves"
            class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                   placeholder-gray-600 focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20"
          />
        </div>

        <div>
          <label for="max-iterations" class="text-[11px] text-gray-400 font-medium block mb-1">Max iterations</label>
          <input
            id="max-iterations"
            type="number"
            bind:value={maxIterations}
            min="1"
            max="20"
            class="w-full px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-sm text-gray-200
                   focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20"
          />
        </div>

        <div class="flex gap-2 pt-1">
          <button
            onclick={applyVerifier}
            class="flex-1 px-3 py-2 rounded-lg bg-orange-600/80 hover:bg-orange-500 text-sm text-white
                   font-medium transition-all duration-150 active:scale-95"
          >
            Apply
          </button>
          {#if selectedNode.data.verifier}
            <button
              onclick={removeVerifier}
              class="px-3 py-2 rounded-lg bg-gray-800 hover:bg-red-900/60 text-sm text-gray-400
                     hover:text-red-300 border border-gray-700 transition-all duration-150"
            >
              Remove
            </button>
          {/if}
        </div>
      </div>

      <button
        onclick={() => { showNodeConfig = false; selectedNode = null; }}
        class="mt-auto px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs text-gray-400
               hover:text-gray-200 border border-gray-700 transition-all duration-150 text-center"
      >
        Close
      </button>
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
</style>
