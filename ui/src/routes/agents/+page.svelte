<script>
	import { onMount } from 'svelte';
	import { fetchAgents } from '$lib/api.js';
	import { agents } from '$lib/stores.js';

	let loading = $state(true);

	const orderedAgents = $derived(
		[...$agents].sort((a, b) => String(b.last_seen || b.created_at || '').localeCompare(String(a.last_seen || a.created_at || '')))
	);
	const activeAgents = $derived(orderedAgents.filter((agent) => agent.status === 'running'));
	const historicalAgents = $derived(orderedAgents.filter((agent) => agent.status !== 'running'));

	onMount(async () => {
		try {
			$agents = await fetchAgents();
		} catch (e) {
			console.error('Failed to load agents:', e);
		} finally {
			loading = false;
		}
	});

	function statusClass(status) {
		if (status === 'running') return 'bg-green-950/70 text-green-300 border-green-900';
		if (status === 'completed') return 'bg-sky-950/70 text-sky-300 border-sky-900';
		if (status === 'failed') return 'bg-red-950/70 text-red-300 border-red-900';
		return 'bg-gray-800 text-gray-300 border-gray-700';
	}

	function taskLabel(agent) {
		const task = agent.parent_task || agent.task;
		if (!task) return 'Legacy row: no task link stored';
		const label = task.description || task.task_id;
		if (task.status === 'killed') return `[stopped] ${label}`;
		if (task.status === 'failed') return `[failed] ${label}`;
		return label;
	}
</script>

<svelte:head>
	<title>Guild - Agents</title>
</svelte:head>

<div class="space-y-6">
	<div class="flex items-end justify-between gap-4">
		<div>
			<h2 class="text-2xl font-bold">Agents</h2>
			<p class="text-sm text-gray-500 mt-1">Local SQLite agent rows, newest activity first.</p>
		</div>
		<div class="flex gap-3 text-sm">
			<div class="rounded border border-gray-800 bg-gray-900 px-3 py-2">
				<span class="text-gray-500">Active</span>
				<span class="ml-2 text-gray-100 font-semibold">{activeAgents.length}</span>
			</div>
			<div class="rounded border border-gray-800 bg-gray-900 px-3 py-2">
				<span class="text-gray-500">History</span>
				<span class="ml-2 text-gray-100 font-semibold">{historicalAgents.length}</span>
			</div>
		</div>
	</div>

	{#if loading}
		<div class="text-gray-400">Loading agents...</div>
	{:else if orderedAgents.length === 0}
		<div class="bg-gray-800 rounded-xl p-8 border border-gray-700 text-center">
			<p class="text-gray-400">No agents registered yet.</p>
			<p class="text-sm text-gray-500 mt-2">Agents are created when tasks are assigned.</p>
		</div>
	{:else}
		<div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
			<table class="w-full">
				<thead>
					<tr class="border-b border-gray-800">
						<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase">Agent</th>
						<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase">Status</th>
						<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase">Task Source</th>
						<th class="px-4 py-3 text-right text-xs text-gray-500 uppercase">Tokens</th>
						<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase">Last Seen</th>
					</tr>
				</thead>
				<tbody>
					{#each orderedAgents as agent}
						<tr class="border-b border-gray-800/70 hover:bg-gray-800/40">
							<td class="px-4 py-3">
								<p class="text-sm font-semibold text-gray-100">{agent.block_name}</p>
								<p class="text-xs font-mono text-gray-500">{agent.agent_id}</p>
							</td>
							<td class="px-4 py-3">
								<span class="inline-flex border px-2 py-0.5 rounded text-xs font-medium {statusClass(agent.status)}">
									{agent.status}
								</span>
							</td>
							<td class="px-4 py-3 max-w-md">
								<p class="text-sm text-gray-300 line-clamp-2">{taskLabel(agent)}</p>
								{#if agent.parent_task}
									<p class="text-xs text-gray-600 mt-1">flow {agent.parent_task.task_id?.slice(0, 8)}</p>
								{:else if agent.task}
									<p class="text-xs text-gray-600 mt-1">task {agent.task.task_id?.slice(0, 8)}</p>
								{/if}
							</td>
							<td class="px-4 py-3 text-right">
								<p class="text-sm text-gray-200">{(agent.token_input || 0).toLocaleString()} in</p>
								<p class="text-xs text-gray-500">{(agent.token_output || 0).toLocaleString()} out</p>
							</td>
							<td class="px-4 py-3 text-sm text-gray-500">
								{agent.last_seen || agent.created_at}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
