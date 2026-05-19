<script>
  import { Handle, Position } from '@xyflow/svelte';

  /** @type {{ data: { blockName: string, role: string, model: string, instructions: string, verifier: string|null, loopUntil: string|null, maxIterations: number|null, children: Array|null, childEdges: Array|null, expanded: boolean, onToggle: Function|null } }} */
  let { data } = $props();

  const roleConfig = {
    planner: { border: 'border-purple-500/70', dot: 'bg-purple-400', accent: 'text-purple-300', icon: '&#9670;' },
    coder: { border: 'border-blue-500/70', dot: 'bg-blue-400', accent: 'text-blue-300', icon: '&#9699;' },
    reviewer: { border: 'border-amber-500/70', dot: 'bg-amber-400', accent: 'text-amber-300', icon: '&#9673;' },
    tester: { border: 'border-green-500/70', dot: 'bg-green-400', accent: 'text-green-300', icon: '&#10003;' },
    verifier: { border: 'border-orange-500/70', dot: 'bg-orange-400', accent: 'text-orange-300', icon: '&#8635;' },
    orchestrator: { border: 'border-red-500/70', dot: 'bg-red-400', accent: 'text-red-300', icon: '&#9733;' },
    implementer: { border: 'border-cyan-500/70', dot: 'bg-cyan-400', accent: 'text-cyan-300', icon: '&#9998;' },
    architect: { border: 'border-indigo-500/70', dot: 'bg-indigo-400', accent: 'text-indigo-300', icon: '&#9651;' },
    agent: { border: 'border-gray-500/70', dot: 'bg-gray-400', accent: 'text-gray-400', icon: '&#9679;' },
  };

  const role = $derived(data.role || 'agent');
  const config = $derived(roleConfig[role] || roleConfig.agent);
  const hasVerifier = $derived(!!data.verifier);
  const hasChildren = $derived(data.children && data.children.length > 0);
  const expanded = $derived(data.expanded || false);

  // Build ordered flow from edges using topological sort
  const orderedFlow = $derived.by(() => {
    if (!data.children || data.children.length === 0) return [];
    if (!data.childEdges || data.childEdges.length === 0) return data.children.map(c => [c]);

    // Build adjacency: source → [targets]
    const adj = {};
    const inDegree = {};
    const nodeMap = {};
    for (const child of data.children) {
      const id = child.data?.blockName || child.blockName || child.id;
      adj[id] = [];
      inDegree[id] = 0;
      nodeMap[id] = child;
    }
    for (const edge of data.childEdges) {
      const src = data.children.find(c => (c.data?.blockName || c.blockName || c.id) === edge.source || c.id === edge.source);
      const tgt = data.children.find(c => (c.data?.blockName || c.blockName || c.id) === edge.target || c.id === edge.target);
      if (src && tgt) {
        const srcId = src.data?.blockName || src.blockName || src.id;
        const tgtId = tgt.data?.blockName || tgt.blockName || tgt.id;
        adj[srcId].push(tgtId);
        inDegree[tgtId] = (inDegree[tgtId] || 0) + 1;
      }
    }

    // BFS topological layers (nodes at same depth = parallel)
    const layers = [];
    let queue = Object.keys(inDegree).filter(k => inDegree[k] === 0);
    const visited = new Set();
    while (queue.length > 0) {
      const layer = queue.map(id => nodeMap[id]).filter(Boolean);
      if (layer.length > 0) layers.push(layer);
      const nextQueue = [];
      for (const id of queue) {
        visited.add(id);
        for (const tgt of (adj[id] || [])) {
          inDegree[tgt]--;
          if (inDegree[tgt] === 0 && !visited.has(tgt)) nextQueue.push(tgt);
        }
      }
      queue = nextQueue;
    }
    // Add any unvisited (disconnected) nodes
    const remaining = data.children.filter(c => !visited.has(c.data?.blockName || c.blockName || c.id));
    if (remaining.length > 0) layers.push(remaining);
    return layers;
  });
</script>

<div class="group relative">
  <!-- Verifier decorator ring -->
  {#if hasVerifier}
    <div class="absolute -top-1 -right-1 -bottom-1 -left-1 rounded-[14px] border-2 border-dashed border-orange-500/40
                bg-orange-950/10"></div>
    <div class="absolute -top-6 right-0 flex items-center gap-1 text-[10px] text-orange-400 font-medium">
      <span>&#8635;</span>
      <span>{data.verifier}</span>
      {#if data.maxIterations}
        <span class="text-orange-600">({data.maxIterations}x)</span>
      {/if}
    </div>
  {/if}

  <div class="rounded-xl border {hasChildren ? 'border-purple-500/60' : config.border} bg-gray-900/95 backdrop-blur-sm
              px-4 py-3.5 min-w-[180px] shadow-xl shadow-black/20
              transition-all duration-200 hover:shadow-2xl hover:shadow-black/30 hover:scale-[1.02]
              {expanded ? 'min-w-[260px]' : ''}">
    <Handle type="target" position={Position.Left}
      class="!w-2.5 !h-2.5 !bg-gray-500 !border-2 !border-gray-800 !rounded-full
             group-hover:!bg-guild-400 !transition-colors" />

    <!-- Header row -->
    <div class="flex items-center gap-2">
      {#if hasChildren}
        <span class="text-xs text-purple-400">&#9646;&#9646;</span>
      {:else}
        <span class="text-xs {config.accent} opacity-70">{@html config.icon}</span>
      {/if}
      <div class="text-sm font-medium text-gray-100 truncate flex-1">
        {data.blockName || 'agent'}
      </div>
      {#if hasChildren}
        <button
          onclick={(e) => { e.stopPropagation(); data.onToggle?.(); }}
          class="p-0.5 rounded hover:bg-purple-900/30 text-purple-400 hover:text-purple-200 transition-colors text-[10px]"
          title="{expanded ? 'Collapse' : 'Expand'}"
        >
          {expanded ? '&#9660;' : '&#9654;'}
        </button>
      {/if}
    </div>

    <!-- Role badge -->
    <div class="flex items-center gap-1.5 mt-1.5">
      <span class="w-1.5 h-1.5 rounded-full {hasChildren ? 'bg-purple-400' : config.dot}"></span>
      <span class="text-[11px] {hasChildren ? 'text-purple-300' : config.accent} font-medium uppercase tracking-wider">
        {hasChildren ? 'block' : role}
      </span>
      {#if hasChildren}
        <span class="text-[9px] text-gray-600 ml-1">{data.children.length} agents</span>
      {/if}
    </div>

    <!-- Loop condition -->
    {#if data.loopUntil && !hasChildren}
      <div class="mt-2 pt-2 border-t border-gray-800 text-[10px] text-gray-500 truncate max-w-[160px]">
        until: {data.loopUntil}
      </div>
    {/if}

    <!-- Expanded: layered flow view -->
    {#if hasChildren && expanded}
      <div class="mt-3 pt-2 border-t border-purple-900/30 max-h-[350px] overflow-y-auto">
        {#each orderedFlow as layer, layerIdx}
          <!-- Parallel agents in this layer -->
          <div class="flex gap-1.5 {layer.length > 1 ? 'justify-center' : ''}">
            {#each layer as child}
              {@const name = child.data?.blockName || child.blockName || 'agent'}
              {@const childRole = child.data?.role || child.role || 'agent'}
              {@const isNested = child.children && child.children.length > 0}
              <div class="flex-1 min-w-0 px-2 py-1.5 rounded-lg bg-gray-800/70 border border-gray-700/40
                          {layer.length > 1 ? 'max-w-[120px]' : ''}">
                <div class="flex items-center gap-1.5">
                  {#if isNested}
                    <span class="text-[8px] text-purple-400">&#9646;&#9646;</span>
                  {:else}
                    <span class="w-1.5 h-1.5 rounded-full bg-guild-400/50 shrink-0"></span>
                  {/if}
                  <span class="text-[10px] font-medium text-gray-200 truncate">{name}</span>
                </div>
                <span class="text-[8px] text-gray-600 uppercase ml-3">{childRole}</span>
              </div>
            {/each}
          </div>
          <!-- Arrow between layers -->
          {#if layerIdx < orderedFlow.length - 1}
            <div class="flex justify-center py-0.5">
              <svg width="20" height="14" class="text-guild-500/60">
                <path d="M10 0 L10 10 M6 7 L10 11 L14 7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            {#if orderedFlow[layerIdx + 1]?.length > 1 && layer.length === 1}
              <div class="flex justify-center -mt-0.5 mb-0.5">
                <span class="text-[8px] text-cyan-600 font-medium uppercase tracking-wider">parallel</span>
              </div>
            {/if}
          {/if}
        {/each}
      </div>
    {/if}

    <Handle type="source" position={Position.Right}
      class="!w-2.5 !h-2.5 !bg-gray-500 !border-2 !border-gray-800 !rounded-full
             group-hover:!bg-guild-400 !transition-colors" />
  </div>
</div>
