<script>
	import { onMount } from 'svelte';
	import { fetchTasks, createTask, killTask } from '$lib/api.js';
	import { taskEvents, tasks } from '$lib/stores.js';

	let loading = true;
	let newTaskDescription = '';
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
			$tasks = await fetchTasks();
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
			await createTask(newTaskDescription);
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
		<h3 class="text-lg font-semibold mb-4">Create Task</h3>
		<form onsubmit={handleCreateTask} class="flex gap-4">
			<input
				type="text"
				bind:value={newTaskDescription}
				placeholder="Describe the task..."
				class="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg
					   text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2
					   focus:ring-guild-500 focus:border-transparent"
			/>
			<button
				type="submit"
				disabled={creating || !newTaskDescription.trim()}
				class="px-6 py-2 bg-guild-600 hover:bg-guild-500 disabled:bg-gray-600
					   disabled:cursor-not-allowed text-white rounded-lg transition-colors
					   font-medium text-sm"
			>
				{creating ? 'Creating...' : 'Create'}
			</button>
		</form>
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
