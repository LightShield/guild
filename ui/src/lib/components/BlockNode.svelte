<script>
  import { Handle, Position } from '@xyflow/svelte';

  /** @type {{ data: { label: string, role: string, blockName: string } }} */
  let { data } = $props();

  const roleColors = {
    planner: { bg: 'bg-purple-900/60', border: 'border-purple-500', accent: 'text-purple-300' },
    coder: { bg: 'bg-blue-900/60', border: 'border-blue-500', accent: 'text-blue-300' },
    reviewer: { bg: 'bg-amber-900/60', border: 'border-amber-500', accent: 'text-amber-300' },
    tester: { bg: 'bg-green-900/60', border: 'border-green-500', accent: 'text-green-300' },
    orchestrator: { bg: 'bg-red-900/60', border: 'border-red-500', accent: 'text-red-300' },
    agent: { bg: 'bg-gray-700/60', border: 'border-gray-500', accent: 'text-gray-300' },
  };

  const role = $derived(data.role || 'agent');
  const colors = $derived(roleColors[role] || roleColors.agent);
</script>

<div class="rounded-lg border-2 {colors.border} {colors.bg} px-4 py-3 min-w-[160px] shadow-lg">
  <Handle type="target" position={Position.Left} class="!w-3 !h-3 !bg-gray-400 !border-2 !border-gray-600" />

  <div class="text-sm font-semibold text-white truncate">
    {data.blockName || data.label}
  </div>
  <div class="text-xs {colors.accent} mt-0.5">
    {role}
  </div>

  <Handle type="source" position={Position.Right} class="!w-3 !h-3 !bg-gray-400 !border-2 !border-gray-600" />
</div>
