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

  // Build a connection map from edges for display
  const connectionMap = $derived.by(() => {
    if (!data.childEdges || !data.children) return {};
    const map = {};
    for (const edge of data.childEdges) {
      const sourceName = data.children.find(c => c.blockName === edge.source || c.id === edge.source);
      const targetName = data.children.find(c => c.blockName === edge.target || c.id === edge.target);
      if (sourceName && targetName) {
        const key = sourceName.blockName || sourceName.id;
        if (!map[key]) map[key] = [];
        map[key].push(targetName.blockName || targetName.id);
      }
    }
    return map;
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

    <!-- Expanded children with connections -->
    {#if hasChildren && expanded}
      <div class="mt-3 pt-2 border-t border-purple-900/30 space-y-1 max-h-[300px] overflow-y-auto">
        {#each data.children as child}
          {@const name = child.data?.blockName || child.blockName || 'agent'}
          {@const childRole = child.data?.role || child.role || 'agent'}
          {@const targets = connectionMap[name] || connectionMap[child.id] || []}
          {@const isComposite = child.children && child.children.length > 0}
          <div class="px-2.5 py-2 rounded-lg bg-gray-800/60 border border-gray-700/40">
            <div class="flex items-center gap-2">
              {#if isComposite}
                <span class="text-[9px] text-purple-400">&#9646;&#9646;</span>
              {:else}
                <span class="w-1.5 h-1.5 rounded-full bg-guild-400/60"></span>
              {/if}
              <span class="text-xs font-medium text-gray-200 flex-1 truncate">{name}</span>
              <span class="text-[9px] text-gray-500 uppercase">{childRole}</span>
            </div>
            {#if targets.length > 0}
              <div class="mt-1 ml-4 flex items-center gap-1 flex-wrap">
                <span class="text-[9px] text-gray-600">&rarr;</span>
                {#each targets as target}
                  <span class="text-[9px] px-1.5 py-0.5 rounded bg-guild-900/40 text-guild-400 border border-guild-800/40">{target}</span>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <Handle type="source" position={Position.Right}
      class="!w-2.5 !h-2.5 !bg-gray-500 !border-2 !border-gray-800 !rounded-full
             group-hover:!bg-guild-400 !transition-colors" />
  </div>
</div>
