<script>
	import { onMount } from 'svelte';
	import { fetchStatus, fetchTasks, fetchAgents, fetchLearnings } from '$lib/api.js';
	import { tasks, agents, status, learnings } from '$lib/stores.js';

	let loading = true;

	onMount(async () => {
		try {
			const [statusData, tasksData, agentsData, learningsData] = await Promise.all([
				fetchStatus(),
				fetchTasks(),
				fetchAgents(),
				fetchLearnings()
			]);
			$status = statusData;
			$tasks = tasksData;
			$agents = agentsData;
			$learnings = learningsData;
		} catch (e) {
			console.error('Failed to load dashboard data:', e);
		} finally {
			loading = false;
		}
	});

	$: runningTasks = $tasks.filter(t => t.status === 'running').length;
	$: totalAgents = $agents.length;
	$: learningsCount = $learnings.length;
</script>

<svelte:head>
	<title>Guild - Dashboard</title>
</svelte:head>

<div class="space-y-8">
	<h2 class="text-2xl font-bold">Dashboard</h2>

	{#if loading}
		<div class="text-gray-400">Loading...</div>
	{:else}
		<!-- Stats Cards -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
			<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
				<p class="text-sm text-gray-400 uppercase tracking-wide">Running Tasks</p>
				<p class="text-3xl font-bold text-guild-400 mt-2">{runningTasks}</p>
			</div>
			<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
				<p class="text-sm text-gray-400 uppercase tracking-wide">Total Agents</p>
				<p class="text-3xl font-bold text-guild-400 mt-2">{totalAgents}</p>
			</div>
			<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
				<p class="text-sm text-gray-400 uppercase tracking-wide">Learnings</p>
				<p class="text-3xl font-bold text-guild-400 mt-2">{learningsCount}</p>
			</div>
		</div>

		<!-- Recent Tasks -->
		<div class="bg-gray-800 rounded-xl border border-gray-700">
			<div class="p-6 border-b border-gray-700 flex items-center justify-between">
				<h3 class="text-lg font-semibold">Recent Tasks</h3>
				<a
					href="/tasks"
					class="text-sm text-guild-400 hover:text-guild-300 transition-colors"
				>
					View all
				</a>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-700">
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Status</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Description</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Created</th>
						</tr>
					</thead>
					<tbody>
						{#each $tasks.slice(0, 10) as task}
							<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
								<td class="px-6 py-3">
									<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
										{task.status === 'running' ? 'bg-green-900/50 text-green-300' :
										 task.status === 'completed' ? 'bg-blue-900/50 text-blue-300' :
										 task.status === 'failed' ? 'bg-red-900/50 text-red-300' :
										 'bg-gray-700 text-gray-300'}">
										{task.status}
									</span>
								</td>
								<td class="px-6 py-3 text-sm">{task.description}</td>
								<td class="px-6 py-3 text-sm text-gray-400">{task.created_at}</td>
							</tr>
						{:else}
							<tr>
								<td colspan="3" class="px-6 py-8 text-center text-gray-500">
									No tasks yet. Create one to get started.
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Quick Actions -->
		<div class="flex gap-4">
			<a
				href="/tasks"
				class="px-4 py-2 bg-guild-600 hover:bg-guild-500 text-white rounded-lg
					   transition-colors font-medium text-sm"
			>
				New Task
			</a>
			<a
				href="/agents"
				class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg
					   transition-colors font-medium text-sm"
			>
				View Agents
			</a>
		</div>
	{/if}
</div>
