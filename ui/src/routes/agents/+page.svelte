<script>
	import { onMount } from 'svelte';
	import { fetchAgents } from '$lib/api.js';
	import { agents } from '$lib/stores.js';

	let loading = true;

	onMount(async () => {
		try {
			$agents = await fetchAgents();
		} catch (e) {
			console.error('Failed to load agents:', e);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Guild - Agents</title>
</svelte:head>

<div class="space-y-8">
	<h2 class="text-2xl font-bold">Agents</h2>

	{#if loading}
		<div class="text-gray-400">Loading agents...</div>
	{:else if $agents.length === 0}
		<div class="bg-gray-800 rounded-xl p-8 border border-gray-700 text-center">
			<p class="text-gray-400">No agents registered yet.</p>
			<p class="text-sm text-gray-500 mt-2">Agents are created when tasks are assigned.</p>
		</div>
	{:else}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
			{#each $agents as agent}
				<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
					<div class="flex items-center justify-between mb-4">
						<h3 class="font-semibold text-sm">{agent.block_name}</h3>
						<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
							{agent.status === 'running' ? 'bg-green-900/50 text-green-300' :
							 agent.status === 'idle' ? 'bg-yellow-900/50 text-yellow-300' :
							 'bg-gray-700 text-gray-300'}">
							{agent.status}
						</span>
					</div>
					<div class="space-y-2 text-sm text-gray-400">
						<p>
							<span class="text-gray-500">ID:</span>
							<span class="font-mono">{agent.agent_id?.slice(0, 12)}</span>
						</p>
						<p>
							<span class="text-gray-500">Tokens in:</span>
							{agent.token_input?.toLocaleString() || 0}
						</p>
						<p>
							<span class="text-gray-500">Tokens out:</span>
							{agent.token_output?.toLocaleString() || 0}
						</p>
						<p>
							<span class="text-gray-500">Created:</span>
							{agent.created_at}
						</p>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
