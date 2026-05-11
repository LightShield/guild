<script>
  import { onMount, onDestroy } from 'svelte';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  let nodes = $state([]);
  let edges = $state([]);
  let messages = $state([]);
  let selectedEdge = $state(null);
  let selectedMessages = $state([]);
  let ws = null;
  let agentPositions = {};
  let agentCount = 0;
  let panelOpen = $state(false);

  // Auto-layout: arrange agents in a circle
  function getAgentPosition(agentId) {
    if (agentPositions[agentId]) return agentPositions[agentId];

    const cols = 3;
    const row = Math.floor(agentCount / cols);
    const col = agentCount % cols;
    const pos = {
      x: 100 + col * 280,
      y: 100 + row * 200,
    };
    agentPositions[agentId] = pos;
    agentCount++;
    return pos;
  }

  function ensureAgentNode(agentId) {
    const existing = nodes.find((n) => n.id === agentId);
    if (existing) return;

    const pos = getAgentPosition(agentId);
    nodes = [
      ...nodes,
      {
        id: agentId,
        type: 'default',
        position: pos,
        data: { label: agentId },
        style: 'background: #1e3a5f; border: 2px solid #38bdf8; border-radius: 8px; padding: 10px; color: #e2e8f0; font-weight: 600;',
      },
    ];
  }

  function getEdgeId(source, target) {
    return `msg-${source}-${target}`;
  }

  function addMessage(msg) {
    messages = [...messages, msg];

    const source = msg.source || msg.from;
    const target = msg.target || msg.to;
    if (!source || !target) return;

    ensureAgentNode(source);
    ensureAgentNode(target);

    const edgeId = getEdgeId(source, target);
    const existingIdx = edges.findIndex((e) => e.id === edgeId);

    if (existingIdx >= 0) {
      // Update existing edge with animation pulse
      const updated = [...edges];
      updated[existingIdx] = {
        ...updated[existingIdx],
        animated: true,
        label: `${(updated[existingIdx]._count || 1) + 1} msgs`,
        _count: (updated[existingIdx]._count || 1) + 1,
        style: 'stroke: #38bdf8; stroke-width: 2px;',
      };
      edges = updated;
    } else {
      edges = [
        ...edges,
        {
          id: edgeId,
          source,
          target,
          animated: true,
          label: '1 msg',
          _count: 1,
          style: 'stroke: #38bdf8; stroke-width: 2px;',
          labelStyle: 'fill: #94a3b8; font-size: 11px;',
        },
      ];
    }

    // Remove animation after a short delay
    setTimeout(() => {
      edges = edges.map((e) => (e.id === edgeId ? { ...e, animated: false } : e));
    }, 2000);
  }

  function handleEdgeClick(_event, edge) {
    selectedEdge = edge;
    const source = edge.source;
    const target = edge.target;
    selectedMessages = messages.filter((m) => {
      const s = m.source || m.from;
      const t = m.target || m.to;
      return (s === source && t === target) || (s === target && t === source);
    });
    panelOpen = true;
  }

  function closePanel() {
    panelOpen = false;
    selectedEdge = null;
    selectedMessages = [];
  }

  onMount(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle direct message events
        if (data.type === 'message' || data.type === 'agent_message') {
          addMessage(data);
          return;
        }

        // Handle messages array in status updates
        if (data.messages && Array.isArray(data.messages)) {
          for (const msg of data.messages) {
            addMessage(msg);
          }
          return;
        }

        // Handle agents list to pre-populate nodes
        if (data.agents && Array.isArray(data.agents)) {
          for (const agent of data.agents) {
            const id = agent.agent_id || agent.block_name || agent.id;
            if (id) ensureAgentNode(id);
          }
        }
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };
  });

  onDestroy(() => {
    if (ws) ws.close();
  });
</script>

<svelte:head>
  <title>Guild - Messages</title>
</svelte:head>

<div class="h-[calc(100vh-4rem)] flex">
  <!-- Flow canvas -->
  <div class="flex-1 relative">
    <div class="absolute top-2 left-2 z-10 bg-gray-800 px-3 py-1.5 rounded text-sm text-gray-300 border border-gray-700">
      <span class="font-semibold text-white">Communication Graph</span>
      <span class="text-gray-500 ml-2">{nodes.length} agents, {messages.length} messages</span>
    </div>

    {#if nodes.length === 0}
      <div class="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
        <div class="bg-gray-800/90 rounded-xl p-8 border border-gray-700 text-center">
          <p class="text-gray-400 text-lg">Waiting for agent messages...</p>
          <p class="text-sm text-gray-500 mt-2">Agents will appear here as they communicate.</p>
        </div>
      </div>
    {/if}

    <SvelteFlow
      {nodes}
      {edges}
      fitView
      onedgeclick={handleEdgeClick}
    >
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </div>

  <!-- Side panel: message detail -->
  {#if panelOpen && selectedEdge}
    <div class="w-96 bg-gray-800 border-l border-gray-700 flex flex-col overflow-hidden">
      <div class="p-4 border-b border-gray-700 flex items-center justify-between">
        <div>
          <h3 class="text-sm font-semibold text-white">Messages</h3>
          <p class="text-xs text-gray-400 mt-0.5">
            {selectedEdge.source} &harr; {selectedEdge.target}
          </p>
        </div>
        <button
          onclick={closePanel}
          class="text-gray-400 hover:text-white text-lg leading-none px-2"
        >
          &times;
        </button>
      </div>

      <div class="flex-1 overflow-y-auto p-4 space-y-3">
        {#each selectedMessages as msg, i}
          <div class="bg-gray-700/50 rounded-lg p-3 border border-gray-600/50">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-medium text-guild-400">
                {msg.source || msg.from}
              </span>
              <span class="text-xs text-gray-500">
                {msg.timestamp || ''}
              </span>
            </div>
            <p class="text-sm text-gray-300 whitespace-pre-wrap break-words">
              {msg.content || msg.text || msg.payload || JSON.stringify(msg)}
            </p>
            {#if msg.port || msg.channel}
              <span class="text-xs text-gray-500 mt-1 block">
                via {msg.port || msg.channel}
              </span>
            {/if}
          </div>
        {:else}
          <p class="text-gray-500 text-sm text-center py-4">No messages found for this edge.</p>
        {/each}
      </div>
    </div>
  {/if}
</div>
