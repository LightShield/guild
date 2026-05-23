<script>
	import { onMount, onDestroy } from 'svelte';
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
	let copiedMap = $state({});
	function copyText(key, text) {
		navigator.clipboard.writeText(text ?? '');
		copiedMap = { ...copiedMap, [key]: true };
		setTimeout(() => { copiedMap = { ...copiedMap, [key]: false }; }, 1500);
	}

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

	function typeDotColor(type) {
		return { workflow: '#a78bfa', workflow_block: '#818cf8', agent: '#2dd4bf', task: '#fb923c' }[type] || 'var(--text-tertiary)';
	}

	let expandedDescIds = $state(new Set());
	function toggleDesc(id, e) {
		e.stopPropagation();
		const s = new Set(expandedDescIds);
		s.has(id) ? s.delete(id) : s.add(id);
		expandedDescIds = s;
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

	let _tasksPoll = null;
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
		_tasksPoll = setInterval(async () => { $tasks = await fetchTasks().catch(() => $tasks); }, 20000);
	});
	onDestroy(() => clearInterval(_tasksPoll));

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
	<title>Guild — Tasks</title>
</svelte:head>

<div class="page animate-fade-in">

	<!-- Header -->
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">execution</div>
			<h1 class="page-title">Tasks</h1>
		</div>
		<button type="button" onclick={async () => ($tasks = await fetchTasks())} class="btn-ghost">Refresh</button>
	</div>

	<!-- Launch form -->
	<div class="panel p-5">
		<form onsubmit={handleCreateTask} class="launch-form">
			<div class="launch-form-top">
				<div class="target-toggle">
					<button type="button" onclick={() => (targetType = 'agent')} class="toggle-btn {targetType === 'agent' ? 'toggle-btn--active' : ''}">Agent</button>
					<button type="button" onclick={() => (targetType = 'workflow')} class="toggle-btn {targetType === 'workflow' ? 'toggle-btn--active' : ''}">Workflow</button>
				</div>
				<span class="launch-hint">{targetType === 'workflow' ? 'Runs a saved composition.' : 'Runs one selected block agent.'}</span>
			</div>
			<div class="launch-inputs">
				{#if targetType === 'workflow'}
					<select bind:value={selectedWorkflow} class="select-field launch-select">
						{#each teams as team}<option value={team.name}>{team.name}</option>{/each}
					</select>
				{:else}
					<select bind:value={selectedAgent} class="select-field launch-select">
						{#each availableBlocks as block}
							<option value={block.name}>{block.name} ({block.role || 'agent'})</option>
						{/each}
						{#if availableBlocks.length === 0}<option value="">Default agent</option>{/if}
					</select>
				{/if}
				<input type="text" bind:value={newTaskDescription}
					placeholder={targetType === 'workflow' ? 'Task for the workflow...' : 'Describe the task...'}
					class="input-field launch-input" />
				<button type="submit"
					disabled={creating || !newTaskDescription.trim() || (targetType === 'workflow' && !selectedWorkflow) || (targetType === 'agent' && availableBlocks.length > 0 && !selectedAgent)}
					class="btn-primary launch-submit">
					{creating ? 'Starting...' : targetType === 'workflow' ? 'Run Workflow' : 'Run Agent'}
				</button>
			</div>
			{#if targetType === 'workflow' && teams.length === 0}
				<p class="launch-warn">No saved workflows. Build one in <a href="/composer-studio" class="link-accent">Composer Studio</a>.</p>
			{/if}
		</form>
	</div>

	<!-- Filters -->
	<div class="filters-row">
		<input type="search" bind:value={search} placeholder="Search id, description, agent..." class="input-field filter-search" style="width: auto; flex: 1" />
		<select bind:value={statusFilter} class="select-field">
			<option value="all">All statuses</option>
			<option value="pending">Pending</option>
			<option value="running">Running</option>
			<option value="completed">Completed</option>
			<option value="failed">Failed</option>
			<option value="killed">Killed</option>
		</select>
		<select bind:value={typeFilter} class="select-field">
			<option value="all">All types</option>
			<option value="workflow">Workflows</option>
			<option value="workflow_block">Blocks</option>
			<option value="agent">Agents</option>
			<option value="task">Tasks</option>
		</select>
		<select bind:value={sortBy} class="select-field">
			<option value="created_at">Created</option>
			<option value="status">Status</option>
			<option value="type">Type</option>
			<option value="agent">Agent</option>
			<option value="description">Description</option>
		</select>
	</div>

	{#if loading}
		<div class="loading-state"><span class="running-dot"></span><span>Loading tasks...</span></div>
	{:else}
		<div class="panel" style="overflow: hidden">
			<table class="data-table">
				<thead>
					<tr class="table-head-row">
						<th class="th"><button class="sort-btn" onclick={() => setSort('created_at')}>ID{sortMarker('created_at')}</button></th>
						<th class="th"><button class="sort-btn" onclick={() => setSort('status')}>Status{sortMarker('status')}</button></th>
						<th class="th"><button class="sort-btn" onclick={() => setSort('type')}>Type{sortMarker('type')}</button></th>
						<th class="th" style="width: 99%"><button class="sort-btn" onclick={() => setSort('description')}>Description{sortMarker('description')}</button></th>
						<th class="th"><button class="sort-btn" onclick={() => setSort('agent')}>Agent{sortMarker('agent')}</button></th>
						<th class="th"><button class="sort-btn" onclick={() => setSort('workflow')}>Origin{sortMarker('workflow')}</button></th>
						<th class="th th--right">Action</th>
					</tr>
				</thead>
				<tbody>
					{#each visibleTasks as task}
						<tr class="data-row row-hover row-{task.status}" onclick={() => toggleTask(task.task_id)}>
							<td class="td td--mono">{task.task_id?.slice(0, 8)}</td>
							<td class="td">
								<div class="status-cell">
									{#if task.status === 'running'}<span class="running-dot"></span>{/if}
									<span class="status-badge status-{task.status}">{task.status}</span>
								</div>
							</td>
							<td class="td td--dim">
								<span class="type-dot" style="background: {typeDotColor(taskKind(task))}; box-shadow: 0 0 5px {typeDotColor(taskKind(task))}88"></span>{typeLabel(taskKind(task))}
							</td>
							<td class="td td--desc">
								<p class="expandable-text {expandedDescIds.has(task.task_id) ? 'expandable-text--open' : ''}" onclick={(e) => toggleDesc(task.task_id, e)}>{task.description}</p>
							</td>
							<td class="td td--dim td--mono">
								<span class="expandable-text {expandedDescIds.has(task.task_id + '_agent') ? 'expandable-text--open' : ''}" style="max-width: 8rem; display: inline-block" onclick={(e) => toggleDesc(task.task_id + '_agent', e)}>{task.assigned_agent || '—'}</span>
							</td>
							<td class="td">
								{#if workflowName(task)}
									<a href={`/workflows?execution=${encodeURIComponent(executionId(task))}`} onclick={(e) => e.stopPropagation()} class="link-accent" style="font-size: 0.72rem">{workflowName(task)}</a>
								{:else}
									<span class="td--dim">direct</span>
								{/if}
							</td>
							<td class="td td--right">
								{#if task.status === 'running' || task.status === 'pending'}
									<button onclick={(e) => handleKillTask(e, task.task_id)} disabled={stoppingTaskId === task.task_id} class="kill-btn">
										{stoppingTaskId === task.task_id ? '...' : 'Stop'}
									</button>
								{/if}
							</td>
						</tr>
						{#if expandedTaskId === task.task_id}
							<tr class="expand-row">
								<td colspan="7" class="expand-cell">
									<div class="expand-grid">
										<div class="expand-label">Task ID</div>
										<div class="expand-value td--mono">{task.task_id}</div>
										<div class="expand-label">Origin</div>
										<div class="expand-value">{workflowName(task) || 'direct'} {#if parentWorkflow(task)}<span class="td--dim">← {parentWorkflow(task).task_id?.slice(0, 8)}</span>{/if}</div>
										<div class="expand-label">Progress</div>
										<div class="copyable-block">
											<button class="copy-btn" onclick={() => copyText(task.task_id, taskProgress(task))}>
												{copiedMap[task.task_id] ? '✓ Copied' : 'Copy'}
											</button>
											<pre class="expand-pre">{taskProgress(task)}</pre>
										</div>
										<div class="expand-label">Timeline</div>
										<div class="timeline">
											{#each eventsForTask(task.task_id) as event}
												<div class="timeline-event">
													<div class="timeline-event-head">
														<span class="timeline-type">{event.event_type}</span>
														<span class="timeline-time">{event.timestamp}</span>
													</div>
													<p class="timeline-msg">{event.message}</p>
												</div>
											{:else}
												<p class="td--dim" style="font-size: 0.72rem">No events yet.</p>
											{/each}
										</div>
									</div>
								</td>
							</tr>
						{/if}
					{:else}
						<tr><td colspan="7" class="empty-row">No matching tasks.</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	.page { display: flex; flex-direction: column; gap: 1.25rem; }

	.page-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
	}
	.page-title {
		font-size: 1.125rem;
		font-weight: 700;
		background: linear-gradient(90deg, var(--text-primary) 60%, var(--text-secondary));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}

	.loading-state {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		font-size: 0.78rem;
		color: var(--text-secondary);
	}

	.launch-form { display: flex; flex-direction: column; gap: 0.875rem; }
	.launch-form-top { display: flex; align-items: center; gap: 1rem; }
	.launch-hint { font-size: 0.68rem; color: var(--text-secondary); }
	.launch-inputs { display: grid; grid-template-columns: 220px 1fr auto; gap: 0.5rem; align-items: center; }
	.launch-select { }
	.launch-input { }
	.launch-submit { white-space: nowrap; }
	.launch-warn { font-size: 0.7rem; color: #fbbf24; }

	.target-toggle {
		display: inline-flex;
		background: var(--bg-base);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		padding: 2px;
		gap: 1px;
	}
	.toggle-btn {
		padding: 0.3rem 0.75rem;
		font-size: 0.68rem;
		font-weight: 600;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		border: none;
		border-radius: 0.1rem;
		cursor: pointer;
		background: transparent;
		color: var(--text-secondary);
		transition: all 0.12s;
	}
	.toggle-btn:hover { color: var(--text-primary); }
	.toggle-btn--active { background: var(--accent); color: #060a12; }

	.filters-row {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.data-table { width: 100%; border-collapse: collapse; }
	.table-head-row { border-bottom: 1px solid var(--border-default); }
	.th {
		padding: 0.625rem 1rem;
		text-align: left;
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--text-secondary);
		white-space: nowrap;
	}
	.th--right { text-align: right; }
	.sort-btn { background: none; border: none; cursor: pointer; color: inherit; font: inherit; letter-spacing: inherit; }
	.sort-btn:hover { color: var(--text-primary); }

	.data-row {
		border-bottom: 1px solid var(--border-subtle);
		cursor: pointer;
	}
	.td {
		padding: 0.625rem 1rem;
		font-size: 0.78rem;
		color: var(--text-primary);
		vertical-align: middle;
	}
	.td--mono { font-size: 0.7rem; color: var(--text-secondary); }
	.td--dim { font-size: 0.75rem; color: var(--text-secondary); }
	.td--desc { max-width: 0; }
	.td--right { text-align: right; }

	.status-cell { display: flex; align-items: center; gap: 0.4rem; }

	.kill-btn {
		padding: 0.2rem 0.5rem;
		font-size: 0.62rem;
		font-weight: 500;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		background: rgba(248, 113, 113, 0.08);
		border: 1px solid rgba(248, 113, 113, 0.2);
		color: #f87171;
		border-radius: 0.1rem;
		cursor: pointer;
		transition: background 0.12s;
	}
	.kill-btn:hover { background: rgba(248, 113, 113, 0.16); }
	.kill-btn:disabled { opacity: 0.4; cursor: not-allowed; }

	.empty-row {
		padding: 2.5rem;
		text-align: center;
		font-size: 0.8rem;
		color: var(--text-secondary);
	}

	.expand-row { background: var(--bg-elevated); }
	.expand-cell { padding: 1rem 1.25rem; }
	.expand-grid {
		display: grid;
		grid-template-columns: 140px 1fr;
		gap: 0.5rem 1rem;
		font-size: 0.78rem;
	}
	.expand-label { color: var(--text-secondary); padding-top: 0.1rem; }
	.expand-value { color: var(--text-primary); word-break: break-all; }
	.expand-pre {
		white-space: pre-wrap;
		word-break: break-words;
		background: var(--bg-base);
		border: 1px solid var(--border-subtle);
		border-radius: 0.15rem;
		padding: 0.625rem 0.75rem;
		font-size: 0.72rem;
		color: var(--text-primary);
		min-height: 4rem;
		font-family: inherit;
		line-height: 1.5;
	}

	.timeline { display: flex; flex-direction: column; gap: 0.375rem; }
	.timeline-event {
		border-left: 2px solid var(--border-default);
		padding-left: 0.625rem;
	}
	.timeline-event-head { display: flex; align-items: center; gap: 0.625rem; }
	.timeline-type { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--accent); }
	.timeline-time { font-size: 0.68rem; color: var(--text-tertiary); }
	.timeline-msg { font-size: 0.72rem; color: var(--text-primary); margin-top: 0.2rem; }
</style>
