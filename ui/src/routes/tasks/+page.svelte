<script>
	import { onMount } from 'svelte';
	import { fetchBlocks, fetchTasks, fetchTeams, createTask, killTask, runBlock, runTeam } from '$lib/api.js';
	import { taskEvents, tasks } from '$lib/stores.js';

	let loading = $state(true);
	let newTaskDescription = $state('');
	let targetType = $state('agent');
	let selectedAgent = $state('');
	let selectedWorkflow = $state('');
	let availableBlocks = $state([]);
	let teams = $state([]);
	let creating = $state(false);
	let expandedTaskId = $state('');
	let stoppingTaskId = $state('');
	let search = $state('');
	let statusFilter = $state('all');
	let typeFilter = $state('all');
	let sortBy = $state('created_at');
	let sortDir = $state('desc');

	const visibleTasks = $derived.by(() => {
		const term = search.trim().toLowerCase();
		return [...$tasks]
			.filter((task) => statusFilter === 'all' || task.status === statusFilter)
			.filter((task) => typeFilter === 'all' || taskKind(task) === typeFilter)
			.filter((task) => {
				if (!term) return true;
				return [task.task_id, task.description, task.assigned_agent, task.status, workflowName(task)]
					.some((value) => String(value || '').toLowerCase().includes(term));
			})
			.sort((a, b) => compareTasks(a, b));
	});

	function eventsForTask(taskId) {
		return $taskEvents.filter((event) => event.task_id === taskId).slice(-10).reverse();
	}

	function parentWorkflow(task) {
		const agent = task.assigned_agent || '';
		const event = $taskEvents.find((item) => item.event_type === 'agent_spawned' && item.agent_id === agent);
		if (!event) return null;
		return $tasks.find((candidate) => candidate.task_id === event.task_id) || null;
	}

	function workflowName(task) {
		const agent = task.assigned_agent || '';
		return task.workflow_name || task.execution_id || parentWorkflow(task)?.assigned_agent || (teams.some((team) => team.name === agent) ? agent : '');
	}

	function executionId(task) {
		return task.execution_id || parentWorkflow(task)?.task_id || task.task_id || '';
	}

	function taskProgress(task) {
		if (task.result) return task.result;
		const latestEvent = eventsForTask(task.task_id)[0];
		return latestEvent?.message || 'Queued. Waiting for the runner to write progress.';
	}

	function taskKind(task) {
		const agent = task.assigned_agent || '';
		if (task.description?.startsWith('[') || /^[A-Za-z0-9_-]+-[0-9a-f]{8}$/.test(agent)) return 'workflow_block';
		if (teams.some((team) => team.name === agent)) return 'workflow';
		if (String(task.result || '').includes('Completed blocks:')) return 'workflow';
		if (workflowName(task) && task.execution_id) return 'workflow';
		return agent && agent !== '-' ? 'agent' : 'task';
	}

	function typeLabel(type) {
		return {
			workflow: 'Workflow',
			workflow_block: 'Workflow block',
			agent: 'Agent',
			task: 'Task',
		}[type] || type;
	}

	function compareTasks(a, b) {
		const values = {
			created_at: [a.created_at, b.created_at],
			status: [a.status, b.status],
			type: [typeLabel(taskKind(a)), typeLabel(taskKind(b))],
			agent: [a.assigned_agent, b.assigned_agent],
			workflow: [workflowName(a), workflowName(b)],
			description: [a.description, b.description],
		}[sortBy] || [a.created_at, b.created_at];
		const result = String(values[0] || '').localeCompare(String(values[1] || ''));
		return sortDir === 'asc' ? result : -result;
	}

	function setSort(nextSort) {
		if (sortBy === nextSort) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		else {
			sortBy = nextSort;
			sortDir = nextSort === 'created_at' ? 'desc' : 'asc';
		}
	}

	function sortMarker(column) {
		if (sortBy !== column) return '';
		return sortDir === 'asc' ? ' up' : ' down';
	}

	function statusClass(status) {
		if (status === 'running') return 'bg-green-900/50 text-green-300';
		if (status === 'completed') return 'bg-blue-900/50 text-blue-300';
		if (status === 'failed') return 'bg-red-900/50 text-red-300';
		if (status === 'killed') return 'bg-amber-900/50 text-amber-300';
		return 'bg-gray-700 text-gray-300';
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

<div class="space-y-6">
	<div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
		<div>
			<h2 class="text-2xl font-bold">Tasks</h2>
			<p class="mt-1 text-sm text-gray-500">Launch agents or workflows, then filter and inspect execution history.</p>
		</div>
		<button type="button" onclick={async () => ($tasks = await fetchTasks())} class="rounded border border-gray-700 px-3 py-2 text-sm text-gray-300 hover:border-guild-500 hover:text-guild-300">
			Refresh
		</button>
	</div>

	<div class="bg-gray-800 rounded-xl p-5 border border-gray-700">
		<form onsubmit={handleCreateTask} class="space-y-4">
			<div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
				<div class="inline-flex rounded border border-gray-700 bg-gray-900 p-1">
					<button type="button" onclick={() => (targetType = 'agent')} class="rounded px-3 py-1.5 text-xs font-semibold transition {targetType === 'agent' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}">Agent</button>
					<button type="button" onclick={() => (targetType = 'workflow')} class="rounded px-3 py-1.5 text-xs font-semibold transition {targetType === 'workflow' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}">Workflow</button>
				</div>
				<p class="text-xs text-gray-500">{targetType === 'workflow' ? 'Runs a saved composition.' : 'Runs one selected block agent.'}</p>
			</div>
			<div class="grid gap-3 lg:grid-cols-[260px_minmax(0,1fr)_auto]">
				{#if targetType === 'workflow'}
					<select bind:value={selectedWorkflow} class="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-guild-500">
						{#each teams as team}
							<option value={team.name}>{team.name}</option>
						{/each}
					</select>
				{:else}
					<select bind:value={selectedAgent} class="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-guild-500">
						{#each availableBlocks as block}
							<option value={block.name}>{block.name} ({block.role || 'agent'})</option>
						{/each}
						{#if availableBlocks.length === 0}
							<option value="">Default agent</option>
						{/if}
					</select>
				{/if}
				<input type="text" bind:value={newTaskDescription} placeholder={targetType === 'workflow' ? 'Task for the workflow...' : 'Task for the selected agent...'} class="min-w-0 px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-guild-500" />
				<button type="submit" disabled={creating || !newTaskDescription.trim() || (targetType === 'workflow' && !selectedWorkflow) || (targetType === 'agent' && availableBlocks.length > 0 && !selectedAgent)} class="px-6 py-2 bg-guild-600 hover:bg-guild-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium text-sm">
					{creating ? 'Starting...' : targetType === 'workflow' ? 'Run Workflow' : 'Run Agent'}
				</button>
			</div>
			{#if targetType === 'workflow' && teams.length === 0}
				<p class="text-xs text-amber-300">No saved workflows yet. Build one in <a href="/composer-studio" class="text-guild-300 hover:text-guild-200">Composer Studio</a>.</p>
			{/if}
		</form>
	</div>

	<div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_150px_170px_160px]">
		<input type="search" bind:value={search} placeholder="Search id, description, agent, workflow..." class="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-guild-500" />
		<select bind:value={statusFilter} class="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100">
			<option value="all">All statuses</option>
			<option value="pending">Pending</option>
			<option value="running">Running</option>
			<option value="completed">Completed</option>
			<option value="failed">Failed</option>
			<option value="killed">Killed</option>
		</select>
		<select bind:value={typeFilter} class="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100">
			<option value="all">All types</option>
			<option value="workflow">Workflows</option>
			<option value="workflow_block">Workflow blocks</option>
			<option value="agent">Agents</option>
			<option value="task">Tasks</option>
		</select>
		<select bind:value={sortBy} class="rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100">
			<option value="created_at">Sort: Created</option>
			<option value="status">Sort: Status</option>
			<option value="type">Sort: Type</option>
			<option value="agent">Sort: Agent</option>
			<option value="workflow">Sort: Workflow</option>
			<option value="description">Sort: Description</option>
		</select>
	</div>

	{#if loading}
		<div class="text-gray-400">Loading tasks...</div>
	{:else}
		<div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead>
						<tr class="border-b border-gray-800">
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('created_at')}>ID{sortMarker('created_at')}</button></th>
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('status')}>Status{sortMarker('status')}</button></th>
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('type')}>Type{sortMarker('type')}</button></th>
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('description')}>Description{sortMarker('description')}</button></th>
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('agent')}>Agent{sortMarker('agent')}</button></th>
							<th class="px-4 py-3 text-left text-xs text-gray-500 uppercase"><button onclick={() => setSort('workflow')}>Origin{sortMarker('workflow')}</button></th>
							<th class="px-4 py-3 text-right text-xs text-gray-500 uppercase">Action</th>
						</tr>
					</thead>
					<tbody>
						{#each visibleTasks as task}
							<tr class="border-b border-gray-800/70 hover:bg-gray-800/40 cursor-pointer" onclick={() => toggleTask(task.task_id)}>
								<td class="px-4 py-3 text-sm font-mono text-gray-500">{task.task_id?.slice(0, 8)}</td>
								<td class="px-4 py-3"><span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {statusClass(task.status)}">{task.status}</span></td>
								<td class="px-4 py-3 text-sm text-gray-300">{typeLabel(taskKind(task))}</td>
								<td class="px-4 py-3 text-sm text-gray-100 max-w-xl"><p class="line-clamp-2">{task.description}</p></td>
								<td class="px-4 py-3 text-sm text-gray-400">{task.assigned_agent || '-'}</td>
								<td class="px-4 py-3 text-sm text-gray-400">
									{#if workflowName(task)}
										<a href={`/workflows?execution=${encodeURIComponent(executionId(task))}`} onclick={(event) => event.stopPropagation()} class="text-guild-400 hover:text-guild-300">{workflowName(task)}</a>
									{:else}
										<span class="text-gray-600">direct</span>
									{/if}
								</td>
								<td class="px-4 py-3 text-right">
									{#if task.status === 'running' || task.status === 'pending'}
										<button onclick={(event) => handleKillTask(event, task.task_id)} disabled={stoppingTaskId === task.task_id} class="px-2.5 py-1 rounded bg-red-950/70 hover:bg-red-900 disabled:bg-gray-800 text-xs text-red-300 disabled:text-gray-500 border border-red-900/60">
											{stoppingTaskId === task.task_id ? 'Stopping' : 'Stop'}
										</button>
									{/if}
								</td>
							</tr>
							{#if expandedTaskId === task.task_id}
								<tr class="border-b border-gray-800/70 bg-gray-950/60">
									<td colspan="7" class="px-4 py-4">
										<div class="grid gap-3 md:grid-cols-[160px_1fr] text-sm">
											<div class="text-gray-500">Task ID</div>
											<div class="font-mono text-gray-300 break-all">{task.task_id}</div>
											<div class="text-gray-500">Origin</div>
											<div class="text-gray-300">{workflowName(task) || 'direct'} {#if parentWorkflow(task)}<span class="text-gray-600">from {parentWorkflow(task).task_id?.slice(0, 8)}</span>{/if}</div>
											<div class="text-gray-500">Progress / Result</div>
											<pre class="whitespace-pre-wrap break-words rounded bg-gray-950 border border-gray-800 p-3 text-xs text-gray-200 min-h-20">{taskProgress(task)}</pre>
											<div class="text-gray-500">Timeline</div>
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
										</div>
									</td>
								</tr>
							{/if}
						{:else}
							<tr><td colspan="7" class="px-6 py-8 text-center text-gray-500">No matching tasks.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
