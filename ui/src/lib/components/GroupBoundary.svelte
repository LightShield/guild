<script>
  import { Handle, Position } from '@xyflow/svelte';

  let { data } = $props();

  const ports = $derived(data.ports || []);
  const inputPorts = $derived(ports.filter((p) => p.direction === 'input'));
  const outputPorts = $derived(ports.filter((p) => p.direction === 'output'));
</script>

<!-- Group boundary: a large dashed-border rectangle behind expanded children -->
<div class="group-boundary">
  <!-- Header bar -->
  <div class="boundary-drag flex items-center gap-2 px-4 py-2.5 border-b border-purple-700/40 bg-purple-950/40 rounded-t-xl cursor-grab active:cursor-grabbing select-none">
    <span class="text-xs text-purple-400">&#9646;&#9646;</span>
    <span class="text-sm font-semibold text-purple-200 flex-1 truncate">{data.blockName || 'block'}</span>
    <span class="text-[9px] text-purple-500 uppercase tracking-wider mr-2">{data.childCount || 0} agents</span>
    <button
      class="px-2 py-0.5 rounded bg-purple-800/60 hover:bg-purple-700/80 text-[10px] text-purple-300
             hover:text-purple-100 border border-purple-700/50 transition-all duration-150"
      onmousedown={(e) => e.stopPropagation()}
      onclick={(e) => { e.stopPropagation(); if (data.onCollapse) data.onCollapse(); }}
    >
      Collapse
    </button>
  </div>

  <!-- Input port handles (left side) -->
  {#each inputPorts as port, i}
    {@const offset = ((i + 1) / (inputPorts.length + 1)) * 100}
    <Handle
      type="target"
      position={Position.Left}
      id={port.handleId}
      style="top: {offset}%;"
      class="!w-3 !h-3 !bg-purple-500 !border-2 !border-purple-900 !rounded-full"
    />
  {/each}

  <!-- Output port handles (right side) -->
  {#each outputPorts as port, i}
    {@const offset = ((i + 1) / (outputPorts.length + 1)) * 100}
    <Handle
      type="source"
      position={Position.Right}
      id={port.handleId}
      style="top: {offset}%;"
      class="!w-3 !h-3 !bg-purple-500 !border-2 !border-purple-900 !rounded-full"
    />
  {/each}

  <!-- Port labels (left) -->
  {#each inputPorts as port, i}
    {@const offset = ((i + 1) / (inputPorts.length + 1)) * 100}
    <div class="port-label port-label-left" style="top: {offset}%;">
      {port.name}
    </div>
  {/each}

  <!-- Port labels (right) -->
  {#each outputPorts as port, i}
    {@const offset = ((i + 1) / (outputPorts.length + 1)) * 100}
    <div class="port-label port-label-right" style="top: {offset}%;">
      {port.name}
    </div>
  {/each}
</div>

<style>
  .group-boundary {
    width: 100%;
    height: 100%;
    border: 2px dashed rgba(167, 139, 250, 0.5);
    border-radius: 0.75rem;
    background: rgba(88, 28, 135, 0.06);
    position: relative;
    min-width: 300px;
    min-height: 200px;
  }

  .port-label {
    position: absolute;
    transform: translateY(-50%);
    font-size: 9px;
    color: rgba(167, 139, 250, 0.7);
    pointer-events: none;
    white-space: nowrap;
  }

  .port-label-left {
    left: 14px;
  }

  .port-label-right {
    right: 14px;
  }
</style>
