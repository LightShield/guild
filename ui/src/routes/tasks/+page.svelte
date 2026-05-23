<script>
	import { onMount } from 'svelte';
	import { fetchBlocks, fetchTasks, fetchTeams, createTask, killTask, runBlock, runTeam } from '$lib/api.js';
	import { taskEvents, tasks } from '$lib/stores.js';

	let loading = true;
	let newTaskDescription = '';
	let targetType = 'agent';
	let selectedAgent = '';
	let selectedWorkflow = '';
	let availableBlocks = [];
	let teams = [];
	let creating = false;
	let expandedTaskId = '';
	let stoppingTaskId = '';

	function eventsForTask(taskId) {
		return $taskEvents.filter((event) => event.task_id === taskId).slice(-8).reverse();
	}

	function taskProgress(task) {
		if (task.result) return task.result;
		const latestEvent = eventsForTask(task.task_id)[0];
		return latestEvent?.message || 'Queued. Waiting for the runner to write progress.';
	}

	function taskKind(task) {
		const agent = task.assigned_agent || '';
		if (task.description?.startsWith('[') || /^[A-Za-z0-9_-]+-[0-9a-f]{8}$/.test(agent)) {
			return 'Workflow block';
		}
		if (agent && agent !== '-') return 'Workflow';
		return 'Single task';
	}

	onMount(async () => {
		try {
			const [loadedTasks, loadedBlocks, loadedTeams] = await Promise.all([
				fetchTasks(),
				fetchBlocks().catch(() => []),
				fetchTeams().catch(() => []),
			]);
			$tasks = loadedTasks;
			availableBlocks = loadedBlocks;
			teams = loadedTeams;
			selectedAgent = loadedBlocks[0]?.name || '';
			selectedWorkflow = loadedTeams[0]?.name || '';
		} catch (e) {
			console.error('Failed to load tasks:', e);
		} finally {
			loading = false;
		}
	});

	async function handleCreateTask(event) {
		event?.preventDefault();
		if (!newTaskDescription.trim()) return;
		creating = true;
		try {
			if (targetType === 'workflow') {
				if (!selectedWorkflow) return;
				await runTeam(selectedWorkflow, newTaskDescription);
			} else if (selectedAgent) {
				await runBlock(selectedAgent, newTaskDescription);
			} else {
				await createTask(newTaskDescription);
			}
			newTaskDescription = '';
			$tasks = await fetchTasks();
		} catch (e) {
			console.error('Failed to create task:', e);
		} finally {
			creating = false;
		}
	}

	function toggleTask(taskId) {
		expandedTaskId = expandedTaskId === taskId ? '' : taskId;
	}

	async function handleKillTask(event, taskId) {
		event.stopPropagation();
		stoppingTaskId = taskId;
		try {
			await killTask(taskId);
			$tasks = await fetchTasks();
		} finally {
			stoppingTaskId = '';
		}
	}
</script>

<svelte:head>
	<title>Guild - Tasks</title>
</svelte:head>

<div class="space-y-8">
	<h2 class="text-2xl font-bold">Tasks</h2>

	<!-- Create Task -->
	<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
		<div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
			<div>
				<h3 class="text-lg font-semibold">Create Task</h3>
				<p class="mt-1 text-sm text-gray-500">Choose a block agent or a saved workflow, then run it.</p>
			</div>
			<div class="inline-flex rounded border border-gray-700 bg-gray-900 p-1">
				<button
					type="button"
					onclick={() => (targetType = 'agent')}
					class="rounded px-3 py-1.5 text-xs font-semibold transition {targetType === 'agent' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}"
				>
					Agent
				</button>
				<button
					type="button"
					onclick={() => (targetType = 'workflow')}
					class="rounded px-3 py-1.5 text-xs font-semibold transition {targetType === 'workflow' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}"
				>
					Workflow
				</button>
			</div>
		</div>
		<form onsubmit={handleCreateTask} class="grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)_auto]">
			{#if targetType === 'workflow'}
				<select
					bind:value={selectedWorkflow}
					class="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-guild-500"
				>
					{#each teams as team}
						<option value={team.name}>{team.name}</option>
					{/each}
				</select>
			{:else}
				<select
					bind:value={selectedAgent}
					class="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-guild-500"
				>
					{#each availableBlocks as block}
						<option value={block.name}>{block.name} ({block.role || 'agent'})</option>
					{/each}
					{#if availableBlocks.length === 0}
						<option value="">Default agent</option>
					{/if}
				</select>
			{/if}
			<input
				type="text"
				bind:value={newTaskDescription}
				placeholder={targetType === 'workflow' ? 'Describe what this workflow should do...' : 'Describe what this agent should do...'}
				class="min-w-0 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg
					   text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2
					   focus:ring-guild-500 focus:border-transparent"
			/>
			<button
				type="submit"
				disabled={creating || !newTaskDescription.trim() || (targetType === 'workflow' && !selectedWorkflow) || (targetType === 'agent' && availableBlocks.length > 0 && !selectedAgent)}
				class="px-6 py-2 bg-guild-600 hover:bg-guild-500 disabled:bg-gray-600
					   disabled:cursor-not-allowed text-white rounded-lg transition-colors
					   font-medium text-sm"
			>
				{creating ? 'Starting...' : targetType === 'workflow' ? 'Run Workflow' : 'Run Agent'}
			</button>
		</form>
		{#if targetType === 'workflow' && teams.length === 0}
			<p class="mt-3 text-xs text-amber-300">No saved workflows yet. Build one in <a href="/composer-studio" class="text-guild-300 hover:text-guild-200">Composer Studio</a>.</p>
		{/if}
	</div>

	<!-- Task List -->
	{#if loading}
		<div class="text-gray-400">Loading tasks...</div>
	{:else}
		<div class="bg-gray-800 rounded-xl border border-gray-700">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-700">
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">ID</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Status</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Description</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Agent</th>
							<th class="px-6 py-3 text-left text-xs text-gray-400 uppercase">Created</th>
							<th class="px-6 py-3 text-right text-xs text-gray-400 uppercase">Action</th>
						</tr>
					</thead>
					<tbody>
						{#each $tasks as task}
							<tr class="border-b border-gray-700/50 hover:bg-gray-700/30 cursor-pointer" onclick={() => toggleTask(task.task_id)}>
								<td class="px-6 py-3 text-sm font-mono text-gray-400">
									{task.task_id?.slice(0, 8)}
								</td>
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
								<td class="px-6 py-3 text-sm text-gray-400">
									{task.assigned_agent || '-'}
								</td>
								<td class="px-6 py-3 text-sm text-gray-400">{task.created_at}</td>
								<td class="px-6 py-3 text-right">
									{#if task.status === 'running' || task.status === 'pending'}
										<button
											onclick={(event) => handleKillTask(event, task.task_id)}
											disabled={stoppingTaskId === task.task_id}
											class="px-2.5 py-1 rounded bg-red-950/70 hover:bg-red-900 disabled:bg-gray-800
											       text-xs text-red-300 disabled:text-gray-500 border border-red-900/60"
										>
											{stoppingTaskId === task.task_id ? 'Stopping' : 'Stop'}
										</button>
									{/if}
								</td>
							</tr>
							{#if expandedTaskId === task.task_id}
								<tr class="border-b border-gray-700/50 bg-gray-900/50">
									<td colspan="6" class="px-6 py-4">
												<div class="grid gap-3 md:grid-cols-[180px_1fr] text-sm">
													<div class="text-gray-500">Task ID</div>
													<div class="font-mono text-gray-300 break-all">{task.task_id}</div>
													<div class="text-gray-500">Type</div>
													<div class="text-gray-300">{taskKind(task)}</div>
													<div class="text-gray-500">Progress / Result</div>
													<pre class="whitespace-pre-wrap break-words rounded-lg bg-gray-950/70 border border-gray-800 p-3 text-xs text-gray-200 min-h-20">{taskProgress(task)}</pre>
											<div class="text-gray-500">Why</div>
											<div class="space-y-2">
												{#each eventsForTask(task.task_id) as event}
													<div class="rounded border border-gray-800 bg-gray-950/60 px-3 py-2">
														<div class="flex items-center gap-2">
															<span class="text-[10px] uppercase tracking-wider text-guild-400">{event.event_type}</span>
															<span class="text-[11px] text-gray-600">{event.timestamp}</span>
														</div>
														<p class="mt-1 text-xs text-gray-300">{event.message}</p>
													</div>
												{:else}
													<p class="text-xs text-gray-500">No timeline events for this task yet.</p>
												{/each}
											</div>
											{#if task.completed_at}
												<div class="text-gray-500">Completed</div>
												<div class="text-gray-300">{task.completed_at}</div>
											{/if}
										</div>
									</td>
								</tr>
							{/if}
						{:else}
							<tr>
								<td colspan="6" class="px-6 py-8 text-center text-gray-500">
									No tasks found.
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
