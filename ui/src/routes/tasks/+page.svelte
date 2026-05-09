<script>
	import { onMount } from 'svelte';
	import { fetchTasks, createTask } from '$lib/api.js';
	import { tasks } from '$lib/stores.js';

	let loading = true;
	let newTaskDescription = '';
	let creating = false;

	onMount(async () => {
		try {
			$tasks = await fetchTasks();
		} catch (e) {
			console.error('Failed to load tasks:', e);
		} finally {
			loading = false;
		}
	});

	async function handleCreateTask() {
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
</script>

<svelte:head>
	<title>Guild - Tasks</title>
</svelte:head>

<div class="space-y-8">
	<h2 class="text-2xl font-bold">Tasks</h2>

	<!-- Create Task -->
	<div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
		<h3 class="text-lg font-semibold mb-4">Create Task</h3>
		<form on:submit|preventDefault={handleCreateTask} class="flex gap-4">
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
						</tr>
					</thead>
					<tbody>
						{#each $tasks as task}
							<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
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
							</tr>
						{:else}
							<tr>
								<td colspan="5" class="px-6 py-8 text-center text-gray-500">
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
