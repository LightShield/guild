<script>
  import { onMount } from 'svelte';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import { fetchBlocks, fetchTeams } from '$lib/api.js';

  let nodes = $state([]);
  let edges = $state([]);
  let availableBlocks = $state([]);
  let teams = $state([]);
  let selectedTeam = $state(null);

  onMount(async () => {
    availableBlocks = await fetchBlocks();
    teams = await fetchTeams();
  });

  function addBlock(block) {
    const id = `${block.name}-${nodes.length}`;
    const newNode = {
      id,
      type: 'default',
      position: { x: 100 + nodes.length * 200, y: 100 + (nodes.length % 3) * 150 },
      data: {
        label: `${block.name}\n(${block.role || 'agent'})`,
      },
    };
    nodes = [...nodes, newNode];
  }

  function loadTeam(team) {
    selectedTeam = team;
    const teamNodes = [];
    const teamEdges = [];
    let x = 50;

    const blockEntries = Object.entries(team.blocks || {});
    for (const [instance, blockType] of blockEntries) {
      teamNodes.push({
        id: instance,
        type: 'default',
        position: { x, y: 100 + (teamNodes.length % 3) * 150 },
        data: { label: `${instance}\n(${blockType})` },
      });
      x += 220;
    }

    for (const conn of team.connections || []) {
      teamEdges.push({
        id: `${conn.source_block}-${conn.target_block}`,
        source: conn.source_block,
        target: conn.target_block,
        label: `${conn.source_port} → ${conn.target_port}`,
      });
    }

    nodes = teamNodes;
    edges = teamEdges;
  }

  function clearCanvas() {
    nodes = [];
    edges = [];
    selectedTeam = null;
  }
</script>

<svelte:head>
  <title>Guild - Team Composer</title>
</svelte:head>

<div class="h-[calc(100vh-4rem)] flex">
  <!-- Sidebar: block palette -->
  <div class="w-64 bg-gray-800 border-r border-gray-700 p-4 overflow-y-auto">
    <h3 class="text-sm font-semibold text-gray-400 uppercase mb-3">Blocks</h3>
    {#each availableBlocks as block}
      <button
        onclick={() => addBlock(block)}
        class="w-full text-left px-3 py-2 mb-1 rounded bg-gray-700 hover:bg-gray-600 text-sm text-gray-200"
      >
        <span class="font-medium">{block.name}</span>
        <span class="text-gray-400 text-xs ml-1">({block.role || ''})</span>
      </button>
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

    <button
      onclick={clearCanvas}
      class="w-full mt-4 px-3 py-2 rounded bg-red-900 hover:bg-red-800 text-sm text-gray-200"
    >
      Clear
    </button>
  </div>

  <!-- Canvas: flow editor -->
  <div class="flex-1 relative">
    {#if selectedTeam}
      <div class="absolute top-2 left-2 z-10 bg-gray-800 px-3 py-1 rounded text-sm text-gray-300">
        Team: <span class="font-bold text-white">{selectedTeam.name}</span>
      </div>
    {/if}
    <SvelteFlow {nodes} {edges} fitView>
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </div>
</div>
