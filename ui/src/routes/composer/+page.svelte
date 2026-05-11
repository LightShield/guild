<script>
  import { onMount } from 'svelte';
  import { SvelteFlow, Controls, Background, MiniMap, useSvelteFlow } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { fetchBlocks, fetchTeams, saveTeam } from '$lib/api.js';
  import BlockNode from '$lib/components/BlockNode.svelte';

  let nodes = $state([]);
  let edges = $state([]);
  let availableBlocks = $state([]);
  let teams = $state([]);
  let selectedTeam = $state(null);
  let teamName = $state('');
  let saveMessage = $state('');
  let draggedBlock = $state(null);

  const nodeTypes = { block: BlockNode };

  onMount(async () => {
    availableBlocks = await fetchBlocks();
    teams = await fetchTeams();
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

    // Get the flow container bounds to compute canvas position
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
      },
    };
    nodes = [...nodes, newNode];
  }

  // --- Fallback click-to-add (kept for accessibility) ---

  function addBlock(block) {
    const position = {
      x: 100 + nodes.length * 200,
      y: 100 + (nodes.length % 3) * 150,
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
      style: 'stroke: #38bdf8; stroke-width: 2px;',
      labelStyle: 'fill: #94a3b8; font-size: 11px;',
    };
    edges = [...edges, newEdge];
  }

  // --- Delete selected nodes/edges ---

  function onKeyDown(event) {
    if (event.key === 'Backspace' || event.key === 'Delete') {
      deleteSelected();
    }
  }

  function deleteSelected() {
    const selectedNodeIds = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
    const selectedEdgeIds = new Set(edges.filter((e) => e.selected).map((e) => e.id));

    if (selectedNodeIds.size === 0 && selectedEdgeIds.size === 0) return;

    // Remove edges connected to deleted nodes, plus selected edges
    edges = edges.filter(
      (e) => !selectedEdgeIds.has(e.id) && !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target)
    );
    nodes = nodes.filter((n) => !selectedNodeIds.has(n.id));
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
        position: { x, y: 100 + (teamNodes.length % 3) * 150 },
        data: {
          label: `${instance} (${name})`,
          blockName: instance,
          role,
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
      saveMessage = `Team "${teamName}" saved.`;
      // Refresh team list
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
  }
</script>

<svelte:head>
  <title>Guild - Team Composer</title>
</svelte:head>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="h-[calc(100vh-4rem)] flex" onkeydown={onKeyDown}>
  <!-- Sidebar: block palette -->
  <div class="w-64 bg-gray-800 border-r border-gray-700 p-4 overflow-y-auto flex flex-col">
    <h3 class="text-sm font-semibold text-gray-400 uppercase mb-3">Blocks</h3>
    <p class="text-xs text-gray-500 mb-2">Drag onto canvas or click to add</p>
    {#each availableBlocks as block}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        draggable="true"
        ondragstart={(e) => onDragStart(e, block)}
        role="button"
        tabindex="0"
        onclick={() => addBlock(block)}
        onkeydown={(e) => e.key === 'Enter' && addBlock(block)}
        class="w-full text-left px-3 py-2 mb-1 rounded bg-gray-700 hover:bg-gray-600
               text-sm text-gray-200 cursor-grab active:cursor-grabbing select-none
               border border-transparent hover:border-gray-500 transition-colors"
      >
        <span class="font-medium">{block.name}</span>
        <span class="text-gray-400 text-xs ml-1">({block.role || 'agent'})</span>
      </div>
    {/each}

    <h3 class="text-sm font-semibold text-gray-400 uppercase mt-6 mb-3">Teams</h3>
    {#each teams as team}
      <button
        onclick={() => loadTeam(team)}
        class="w-full text-left px-3 py-2 mb-1 rounded bg-gray-700 hover:bg-gray-600 text-sm text-gray-200"
      >
        {team.name}
      </button>
    {/each}

    <!-- Save section -->
    <div class="mt-6 border-t border-gray-700 pt-4">
      <h3 class="text-sm font-semibold text-gray-400 uppercase mb-2">Save Team</h3>
      <input
        type="text"
        bind:value={teamName}
        placeholder="Team name..."
        class="w-full px-3 py-1.5 rounded bg-gray-700 border border-gray-600 text-sm text-gray-200
               placeholder-gray-500 focus:outline-none focus:border-guild-400 mb-2"
      />
      <button
        onclick={handleSave}
        class="w-full px-3 py-2 rounded bg-guild-600 hover:bg-guild-500 text-sm text-white font-medium transition-colors"
      >
        Save Team
      </button>
      {#if saveMessage}
        <p class="text-xs mt-1.5 {saveMessage.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">
          {saveMessage}
        </p>
      {/if}
    </div>

    <!-- Actions -->
    <div class="mt-4 space-y-2">
      <button
        onclick={deleteSelected}
        class="w-full px-3 py-2 rounded bg-gray-700 hover:bg-gray-600 text-sm text-gray-200 transition-colors"
      >
        Delete Selected
      </button>
      <button
        onclick={clearCanvas}
        class="w-full px-3 py-2 rounded bg-red-900 hover:bg-red-800 text-sm text-gray-200 transition-colors"
      >
        Clear All
      </button>
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
      <div class="absolute top-2 left-2 z-10 bg-gray-800 px-3 py-1 rounded text-sm text-gray-300 border border-gray-700">
        Team: <span class="font-bold text-white">{selectedTeam.name}</span>
      </div>
    {/if}

    {#if nodes.length === 0}
      <div class="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
        <div class="bg-gray-800/80 rounded-xl p-8 border border-gray-700 text-center">
          <p class="text-gray-400">Drag blocks here to start composing a team</p>
          <p class="text-xs text-gray-500 mt-2">Connect nodes by dragging from handle to handle</p>
        </div>
      </div>
    {/if}

    <SvelteFlow
      {nodes}
      {edges}
      {nodeTypes}
      fitView
      onconnect={onConnect}
      deleteKey="Backspace"
    >
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </div>
</div>
