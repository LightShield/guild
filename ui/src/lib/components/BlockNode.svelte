<script>
  import { Handle, Position } from '@xyflow/svelte';

  let { data, id } = $props();

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
  const isComposite = $derived(data.type === 'composite');
  const ports = $derived(data.ports || []);
  const inputPorts = $derived(ports.filter((p) => p.direction === 'input'));
  const outputPorts = $derived(ports.filter((p) => p.direction === 'output'));
  const showPortLabels = $derived(inputPorts.length > 1 || outputPorts.length > 1);
</script>

<div class="group relative">
  <div class="rounded-xl border {isComposite ? 'border-purple-500/60' : config.border} bg-gray-900/95 backdrop-blur-sm
              px-4 py-3.5 min-w-[180px] shadow-xl shadow-black/20
              transition-all duration-200 hover:shadow-2xl hover:shadow-black/30 hover:scale-[1.02]
              {isComposite ? 'cursor-pointer' : ''}">

    <!-- Input handles (left side) -->
    {#each inputPorts as port, i}
      {@const offset = inputPorts.length === 1 ? 50 : 30 + (i * 40 / Math.max(inputPorts.length - 1, 1))}
      <Handle
        type="target"
        position={Position.Left}
        id={port.handleId}
        style="top: {offset}%;"
        class="!w-2.5 !h-2.5 !bg-gray-500 !border-2 !border-gray-800 !rounded-full
               group-hover:!bg-guild-400 !transition-colors"
      />
    {/each}

    <!-- Header row -->
    <div class="flex items-center gap-2">
      {#if isComposite}
        <span class="text-xs text-purple-400">&#9646;&#9646;</span>
      {:else}
        <span class="text-xs {config.accent} opacity-70">{@html config.icon}</span>
      {/if}
      <div class="text-sm font-medium text-gray-100 truncate flex-1">
        {data.blockName || 'agent'}
      </div>
    </div>

    <!-- Role badge -->
    <div class="flex items-center gap-1.5 mt-1.5">
      <span class="w-1.5 h-1.5 rounded-full {isComposite ? 'bg-purple-400' : config.dot}"></span>
      <span class="text-[11px] {isComposite ? 'text-purple-300' : config.accent} font-medium uppercase tracking-wider">
        {isComposite ? 'block' : role}
      </span>
      {#if isComposite}
        <span class="text-[9px] text-gray-600 ml-1">{data.childCount || '?'} agents</span>
      {/if}
    </div>

    <!-- Port labels (when multiple) -->
    {#if showPortLabels}
      <div class="mt-2 pt-2 border-t border-gray-800 flex justify-between text-[9px] text-gray-500">
        <div class="space-y-0.5">
          {#each inputPorts as port}
            <div class="text-left">{port.name}</div>
          {/each}
        </div>
        <div class="space-y-0.5">
          {#each outputPorts as port}
            <div class="text-right">{port.name}</div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Output handles (right side) -->
    {#each outputPorts as port, i}
      {@const offset = outputPorts.length === 1 ? 50 : 30 + (i * 40 / Math.max(outputPorts.length - 1, 1))}
      <Handle
        type="source"
        position={Position.Right}
        id={port.handleId}
        style="top: {offset}%;"
        class="!w-2.5 !h-2.5 !bg-gray-500 !border-2 !border-gray-800 !rounded-full
               group-hover:!bg-guild-400 !transition-colors"
      />
    {/each}
  </div>
</div>
