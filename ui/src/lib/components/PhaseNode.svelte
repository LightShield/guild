<script>
  /** @type {{ data: { label: string, execution: string, phaseIndex: number } }} */
  let { data } = $props();

  const execColor = $derived(data.execution === 'parallel' ? 'border-cyan-700/50 bg-cyan-950/20' : 'border-gray-700/50 bg-gray-900/30');
</script>

<div class="rounded-2xl border-2 border-dashed {execColor} px-6 py-4 min-w-[220px] min-h-[120px]">
  <div class="flex items-center gap-2 mb-2">
    <span class="text-[10px] font-bold text-gray-600 uppercase tracking-widest">Phase {data.phaseIndex + 1}</span>
    <span class="text-xs font-semibold text-gray-300">{data.label}</span>
    {#if data.execution === 'parallel'}
      <span class="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-cyan-900/50 text-cyan-400 font-medium uppercase">parallel</span>
    {/if}
  </div>
</div>
