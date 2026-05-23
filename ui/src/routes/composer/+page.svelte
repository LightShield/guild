<script>
	import { onMount } from 'svelte';
	import { fetchTasks, fetchTeams, fetchWorkflows } from '$lib/api.js';
	import { tasks } from '$lib/stores.js';

	let loading = $state(true);
	let teams = $state([]);
	let workflowRecords = $state([]);
	let apiNotice = $state('');

	const workflowTasks = $derived.by(() => {
		const records = workflowRecords.length ? workflowRecords : $tasks;
		return [...records]
			.filter((task) => isWorkflowTask(task))
			.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
	});
	const activeWorkflows = $derived(workflowTasks.filter((task) => ['pending', 'running', 'paused', 'blocked'].includes(task.status)));
	const recentWorkflows = $derived(workflowTasks.filter((task) => !['pending', 'running', 'paused', 'blocked'].includes(task.status)).slice(0, 6));

	onMount(loadComposer);

	async function loadComposer() {
		loading = true;
		apiNotice = '';
		try {
			const [loadedTeams, loadedTasks, loadedWorkflows] = await Promise.all([
				fetchTeams().catch(() => []),
				fetchTasks().catch(() => []),
				fetchWorkflows().catch((error) => {
					apiNotice = `Workflow API unavailable: ${error.message}`;
					return [];
				})
			]);
			teams = loadedTeams;
			$tasks = loadedTasks;
			workflowRecords = loadedWorkflows;
		} finally {
			loading = false;
		}
	}

	function isWorkflowTask(task) {
		const agent = task.assigned_agent || '';
		if (!agent || task.description?.startsWith('[')) return false;
		if (/^[A-Za-z0-9_-]+-[0-9a-f]{8}$/.test(agent)) return false;
		return task.execution_id || String(task.result || '').includes('Completed blocks:') || agent !== 'agent';
	}

	function executionId(workflow) {
		return workflow?.execution_id || workflow?.task_id || '';
	}

	function shortId(id) {
		return id?.slice(0, 8) || '-';
	}

	function statusClass(status) {
		if (status === 'running') return 'border-emerald-700 bg-emerald-950/50 text-emerald-300';
		if (status === 'completed') return 'border-sky-700 bg-sky-950/50 text-sky-300';
		if (status === 'failed') return 'border-red-800 bg-red-950/60 text-red-300';
		return 'border-gray-700 bg-gray-900 text-gray-300';
	}
</script>

<svelte:head>
	<title>Guild - Composer</title>
</svelte:head>

<div class="space-y-6">
	<div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
		<div>
			<h2 class="text-2xl font-bold text-gray-100">Composer</h2>
			<p class="mt-1 text-sm text-gray-500">Start from saved flows, open the visual studio, and inspect running compositions.</p>
		</div>
		<div class="flex flex-wrap gap-2">
			<a href="/composer-studio" class="rounded border border-guild-600 bg-guild-600 px-4 py-2 text-sm font-semibold text-white hover:bg-guild-500">
				Open Composer Studio
			</a>
			<a href="/workflows" class="rounded border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:border-guild-500 hover:text-guild-300">
				View Workflows
			</a>
		</div>
	</div>

	{#if apiNotice}
		<div class="flex items-center justify-between gap-4 rounded border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
			<p>{apiNotice}</p>
			<button type="button" onclick={loadComposer} class="rounded border border-amber-700 px-3 py-1.5 text-xs text-amber-100 hover:bg-amber-900/40">
				Retry
			</button>
		</div>
	{/if}

	{#if loading}
		<div class="text-gray-400">Loading composer...</div>
	{:else}
		<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
			<section class="space-y-4">
				<div class="grid gap-3 sm:grid-cols-3">
					<div class="rounded border border-gray-800 bg-gray-900 px-4 py-3">
						<p class="text-[11px] uppercase text-gray-500">Saved Flows</p>
						<p class="mt-1 text-2xl font-semibold text-gray-100">{teams.length}</p>
					</div>
					<div class="rounded border border-gray-800 bg-gray-900 px-4 py-3">
						<p class="text-[11px] uppercase text-gray-500">Active</p>
						<p class="mt-1 text-2xl font-semibold text-emerald-300">{activeWorkflows.length}</p>
					</div>
					<div class="rounded border border-gray-800 bg-gray-900 px-4 py-3">
						<p class="text-[11px] uppercase text-gray-500">Recent Runs</p>
						<p class="mt-1 text-2xl font-semibold text-sky-300">{recentWorkflows.length}</p>
					</div>
				</div>

				<div class="rounded border border-gray-800 bg-gray-900">
					<div class="flex items-center justify-between border-b border-gray-800 px-4 py-3">
						<div>
							<h3 class="text-sm font-semibold text-gray-100">Saved Flows</h3>
							<p class="text-xs text-gray-500">Open a flow in Studio to edit or run it.</p>
						</div>
						<a href="/composer-studio" class="text-xs font-semibold text-guild-400 hover:text-guild-300">New / Edit</a>
					</div>
					<div class="divide-y divide-gray-800">
						{#each teams as team}
							<a href={`/composer-studio?team=${encodeURIComponent(team.name)}`} class="block px-4 py-3 hover:bg-gray-800/60">
								<div class="flex items-center justify-between gap-3">
									<p class="truncate text-sm font-semibold text-gray-100">{team.name}</p>
									<span class="text-xs text-gray-500">Open</span>
								</div>
								<p class="mt-1 text-xs text-gray-500">{team.blocks?.length || Object.keys(team.blocks || {}).length || 0} blocks</p>
							</a>
						{:else}
							<div class="px-4 py-8 text-center text-sm text-gray-500">
								No saved flows yet. Open Studio to create one.
							</div>
						{/each}
					</div>
				</div>
			</section>

			<aside class="space-y-4">
				<div class="rounded border border-gray-800 bg-gray-900">
					<div class="border-b border-gray-800 px-4 py-3">
						<h3 class="text-sm font-semibold text-gray-100">Active Workflows</h3>
						<p class="text-xs text-gray-500">Running or queued executions.</p>
					</div>
					<div class="space-y-2 p-3">
						{#each activeWorkflows as workflow}
							<a href={`/workflows?execution=${encodeURIComponent(executionId(workflow))}`} class="block rounded border border-gray-800 bg-gray-950/60 p-3 hover:border-guild-700">
								<div class="flex items-center justify-between gap-3">
									<p class="truncate text-sm font-semibold text-gray-100">{workflow.assigned_agent}</p>
									<span class="rounded border px-2 py-0.5 text-[11px] {statusClass(workflow.status)}">{workflow.status}</span>
								</div>
								<p class="mt-2 line-clamp-2 text-xs text-gray-400">{workflow.description}</p>
								<p class="mt-2 font-mono text-[11px] text-gray-600">exec {shortId(executionId(workflow))}</p>
							</a>
						{:else}
							<p class="px-1 py-5 text-center text-sm text-gray-600">No active workflows.</p>
						{/each}
					</div>
				</div>

				<div class="rounded border border-gray-800 bg-gray-900">
					<div class="border-b border-gray-800 px-4 py-3">
						<h3 class="text-sm font-semibold text-gray-100">Recent Results</h3>
						<p class="text-xs text-gray-500">Completed and failed runs.</p>
					</div>
					<div class="space-y-2 p-3">
						{#each recentWorkflows as workflow}
							<a href={`/workflows?execution=${encodeURIComponent(executionId(workflow))}`} class="block rounded border border-gray-800 bg-gray-950/60 p-3 hover:border-guild-700">
								<div class="flex items-center justify-between gap-3">
									<p class="truncate text-sm font-semibold text-gray-100">{workflow.assigned_agent}</p>
									<span class="rounded border px-2 py-0.5 text-[11px] {statusClass(workflow.status)}">{workflow.status}</span>
								</div>
								<p class="mt-2 font-mono text-[11px] text-gray-600">exec {shortId(executionId(workflow))}</p>
							</a>
						{:else}
							<p class="px-1 py-5 text-center text-sm text-gray-600">No finished workflows yet.</p>
						{/each}
					</div>
				</div>
			</aside>
		</div>
	{/if}
</div>
