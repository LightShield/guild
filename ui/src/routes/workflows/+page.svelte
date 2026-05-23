<script>
	import { onMount } from 'svelte';
	import { fetchTasks, fetchWorkflow, fetchWorkflows } from '$lib/api.js';
	import { taskEvents, tasks } from '$lib/stores.js';

	let loading = true;
	let selectedWorkflowId = '';
	let workflowRecords = [];
	let selectedRecord = null;
	let fullEvents = [];
	let childEvents = [];
	let copied = '';

	const workflowTasks = $derived.by(() => {
		const apiRecords = workflowRecords.length ? workflowRecords : $tasks;
		return [...apiRecords]
			.filter((task) => isWorkflowTask(task))
			.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
	});

	const activeWorkflows = $derived(
		workflowTasks.filter((task) => ['pending', 'running', 'paused', 'blocked'].includes(task.status))
	);
	const pastWorkflows = $derived(
		workflowTasks.filter((task) => !['pending', 'running', 'paused', 'blocked'].includes(task.status))
	);
	const selectedWorkflow = $derived(
		workflowTasks.find((task) => executionId(task) === selectedWorkflowId) ||
			activeWorkflows[0] ||
			pastWorkflows[0] ||
			null
	);
	const selectedEvents = $derived.by(() => {
		if (!selectedWorkflow) return [];
		const liveEvents = $taskEvents.filter((event) => event.task_id === executionId(selectedWorkflow));
		const events = fullEvents.length ? fullEvents : liveEvents;
		return [...events].sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')));
	});
	const selectedBlockRuns = $derived.by(() => {
		if (!selectedWorkflow) return [];
		const apiChildren = selectedRecord?.child_tasks || selectedWorkflow.child_tasks || [];
		const apiChildEvents = childEvents.length ? childEvents : [];
		const spawned = selectedEvents.filter((event) => event.event_type === 'agent_spawned' && event.agent_id);
		return spawned.map((event) => {
			const childTask =
				apiChildren.find((task) => task.assigned_agent === event.agent_id) ||
				$tasks.find((task) => task.assigned_agent === event.agent_id);
			const blockEvents = [...apiChildEvents, ...$taskEvents]
				.filter((item) => item.agent_id === event.agent_id)
				.sort((a, b) => String(a.timestamp || '').localeCompare(String(b.timestamp || '')));
			return {
				agentId: event.agent_id,
				blockName: event.block_name || event.message || 'block',
				status: childTask?.status || statusFromEvents(blockEvents),
				result: childTask?.result || latestMessage(blockEvents),
				task: childTask,
				events: blockEvents
			};
		});
	});

	$effect(() => {
		if (selectedWorkflow && executionId(selectedWorkflow) !== selectedWorkflowId) {
			selectWorkflow(executionId(selectedWorkflow));
		}
	});

	onMount(async () => {
		try {
			workflowRecords = await fetchWorkflows();
			$tasks = await fetchTasks();
		} finally {
			loading = false;
		}
	});

	function isWorkflowTask(task) {
		const agent = task.assigned_agent || '';
		if (!agent) return false;
		if (task.description?.startsWith('[')) return false;
		if (/^[A-Za-z0-9_-]+-[0-9a-f]{8}$/.test(agent)) return false;
		return (
			task.execution_id ||
			String(task.result || '').includes('Completed blocks:') ||
			$taskEvents.some((event) => event.task_id === task.task_id && event.event_type.startsWith('block_')) ||
			agent !== 'agent'
		);
	}

	async function selectWorkflow(taskId) {
		selectedWorkflowId = taskId;
		selectedRecord = null;
		fullEvents = [];
		childEvents = [];
		copied = '';
		try {
			selectedRecord = await fetchWorkflow(taskId);
			fullEvents = selectedRecord.events || [];
			childEvents = selectedRecord.child_events || [];
		} catch (error) {
			console.error('Failed to load workflow execution:', error);
		}
	}

	function statusFromEvents(events) {
		const last = events.at(-1);
		if (!last) return 'unknown';
		if (last.event_type === 'failed') return 'failed';
		if (last.event_type === 'completed') return 'completed';
		if (last.event_type === 'provider_wait' || last.event_type === 'running') return 'running';
		return last.event_type;
	}

	function latestMessage(events) {
		return events.at(-1)?.message || '';
	}

	function statusClass(status) {
		if (status === 'running') return 'border-emerald-700 bg-emerald-950/50 text-emerald-300';
		if (status === 'completed') return 'border-sky-700 bg-sky-950/50 text-sky-300';
		if (status === 'failed') return 'border-red-800 bg-red-950/60 text-red-300';
		if (status === 'killed') return 'border-amber-800 bg-amber-950/50 text-amber-300';
		return 'border-gray-700 bg-gray-900 text-gray-300';
	}

	function workflowOutput(task) {
		if (selectedRecord?.execution_id === executionId(task) && selectedRecord.output) {
			return selectedRecord.output;
		}
		if (task?.output) return task.output;
		const result = String(task?.result || '');
		const match = result.match(/Latest output:\n([\s\S]*)$/);
		return (match?.[1] || result || '').trim();
	}

	function executionId(workflow) {
		return workflow?.execution_id || workflow?.task_id || '';
	}

	function shortId(id) {
		return id?.slice(0, 8) || '-';
	}

	async function copyText(label, text) {
		await navigator.clipboard.writeText(text || '');
		copied = label;
		setTimeout(() => {
			if (copied === label) copied = '';
		}, 1400);
	}
</script>

<svelte:head>
	<title>Guild - Workflows</title>
</svelte:head>

<div class="space-y-6">
	<div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
		<div>
			<h2 class="text-2xl font-bold text-gray-100">Workflows</h2>
			<p class="mt-1 text-sm text-gray-500">Live and historical composed runs, grouped by flow.</p>
		</div>
		<div class="grid grid-cols-3 gap-2 text-sm">
			<div class="rounded border border-gray-800 bg-gray-900 px-3 py-2">
				<p class="text-[11px] uppercase text-gray-500">Active</p>
				<p class="text-lg font-semibold text-emerald-300">{activeWorkflows.length}</p>
			</div>
			<div class="rounded border border-gray-800 bg-gray-900 px-3 py-2">
				<p class="text-[11px] uppercase text-gray-500">History</p>
				<p class="text-lg font-semibold text-gray-200">{pastWorkflows.length}</p>
			</div>
			<div class="rounded border border-gray-800 bg-gray-900 px-3 py-2">
				<p class="text-[11px] uppercase text-gray-500">Blocks</p>
				<p class="text-lg font-semibold text-sky-300">{selectedBlockRuns.length}</p>
			</div>
		</div>
	</div>

	{#if loading}
		<div class="text-gray-400">Loading workflows...</div>
	{:else if workflowTasks.length === 0}
		<div class="rounded-lg border border-gray-800 bg-gray-900 p-8 text-center text-gray-500">
			No workflow runs yet.
		</div>
	{:else}
		<div class="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
			<aside class="space-y-4">
				<section>
					<h3 class="mb-2 text-xs font-semibold uppercase text-gray-500">Active Workflows</h3>
					<div class="space-y-2">
						{#each activeWorkflows as workflow}
							<button
								type="button"
								onclick={() => selectWorkflow(executionId(workflow))}
								class="w-full rounded border p-3 text-left transition
									{executionId(selectedWorkflow) === executionId(workflow) ? 'border-guild-500 bg-guild-950/30' : 'border-gray-800 bg-gray-900 hover:border-gray-700'}"
							>
								<div class="flex items-center justify-between gap-3">
									<p class="truncate text-sm font-semibold text-gray-100">{workflow.assigned_agent}</p>
									<span class="rounded border px-2 py-0.5 text-[11px] {statusClass(workflow.status)}">{workflow.status}</span>
								</div>
								<p class="mt-2 line-clamp-2 text-xs text-gray-400">{workflow.description}</p>
								<p class="mt-2 font-mono text-[11px] text-gray-600">exec {shortId(executionId(workflow))}</p>
							</button>
						{:else}
							<p class="rounded border border-gray-800 bg-gray-900 px-3 py-4 text-sm text-gray-600">No active workflows.</p>
						{/each}
					</div>
				</section>

				<section>
					<h3 class="mb-2 text-xs font-semibold uppercase text-gray-500">Completed / Failed</h3>
					<div class="max-h-[52vh] space-y-2 overflow-y-auto pr-1">
						{#each pastWorkflows as workflow}
							<button
								type="button"
								onclick={() => selectWorkflow(executionId(workflow))}
								class="w-full rounded border p-3 text-left transition
									{executionId(selectedWorkflow) === executionId(workflow) ? 'border-guild-500 bg-guild-950/30' : 'border-gray-800 bg-gray-900 hover:border-gray-700'}"
							>
								<div class="flex items-center justify-between gap-3">
									<p class="truncate text-sm font-semibold text-gray-100">{workflow.assigned_agent}</p>
									<span class="rounded border px-2 py-0.5 text-[11px] {statusClass(workflow.status)}">{workflow.status}</span>
								</div>
								<p class="mt-2 line-clamp-2 text-xs text-gray-400">{workflow.description}</p>
								<p class="mt-2 font-mono text-[11px] text-gray-600">exec {shortId(executionId(workflow))}</p>
								<p class="mt-2 text-[11px] text-gray-600">{workflow.completed_at || workflow.created_at}</p>
							</button>
						{/each}
					</div>
				</section>
			</aside>

			{#if selectedWorkflow}
				<section class="space-y-4">
					<div class="rounded-lg border border-gray-800 bg-gray-900 p-4">
						<div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
							<div>
								<div class="flex flex-wrap items-center gap-2">
									<h3 class="text-lg font-semibold text-gray-100">{selectedWorkflow.assigned_agent}</h3>
									<span class="rounded border px-2 py-0.5 text-xs {statusClass(selectedWorkflow.status)}">{selectedWorkflow.status}</span>
								</div>
								<p class="mt-2 text-sm text-gray-400">{selectedWorkflow.description}</p>
								<div class="mt-2 flex flex-wrap items-center gap-2">
									<p class="font-mono text-xs text-gray-600">execution_id={executionId(selectedWorkflow)}</p>
									<button
										type="button"
										onclick={() => copyText('execution', executionId(selectedWorkflow))}
										class="rounded border border-gray-800 px-2 py-1 text-[11px] text-gray-400 hover:border-guild-500 hover:text-guild-300"
									>
										{copied === 'execution' ? 'Copied ID' : 'Copy ID'}
									</button>
								</div>
							</div>
							<button
								type="button"
								onclick={() => copyText('workflow', workflowOutput(selectedWorkflow))}
								class="rounded border border-gray-700 px-3 py-2 text-xs text-gray-300 hover:border-guild-500 hover:text-guild-300"
							>
								{copied === 'workflow' ? 'Copied' : 'Copy output'}
							</button>
						</div>
					</div>

					<div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
						<div class="space-y-4">
							<div class="rounded-lg border border-gray-800 bg-gray-900 p-4">
								<div class="mb-3 flex items-center justify-between">
									<h4 class="text-sm font-semibold uppercase text-gray-500">Workflow Output</h4>
									<span class="text-xs text-gray-600">{selectedWorkflow.completed_at || selectedWorkflow.created_at}</span>
								</div>
								<pre class="max-h-[42vh] overflow-auto whitespace-pre-wrap rounded border border-gray-800 bg-gray-950 p-4 text-sm leading-6 text-gray-200">{workflowOutput(selectedWorkflow) || 'No output written yet.'}</pre>
							</div>

							<div class="rounded-lg border border-gray-800 bg-gray-900 p-4">
								<h4 class="mb-3 text-sm font-semibold uppercase text-gray-500">Block Runs</h4>
								<div class="space-y-3">
									{#each selectedBlockRuns as block}
										<div class="rounded border border-gray-800 bg-gray-950/60 p-3">
											<div class="flex flex-wrap items-center justify-between gap-2">
												<div>
													<p class="text-sm font-semibold text-gray-100">{block.blockName}</p>
													<p class="font-mono text-[11px] text-gray-600">{block.agentId}</p>
												</div>
												<span class="rounded border px-2 py-0.5 text-[11px] {statusClass(block.status)}">{block.status}</span>
											</div>
											{#if block.result}
												<pre class="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-gray-800 bg-gray-950 p-3 text-xs leading-5 text-gray-300">{block.result}</pre>
												<button
													type="button"
													onclick={() => copyText(block.agentId, block.result)}
													class="mt-2 text-xs text-guild-400 hover:text-guild-300"
												>
													{copied === block.agentId ? 'Copied block output' : 'Copy block output'}
												</button>
											{/if}
										</div>
									{:else}
										<p class="text-sm text-gray-600">No block agents recorded for this workflow.</p>
									{/each}
								</div>
							</div>
						</div>

						<div class="rounded-lg border border-gray-800 bg-gray-900 p-4">
							<h4 class="mb-3 text-sm font-semibold uppercase text-gray-500">Timeline</h4>
							<div class="space-y-3">
								{#each selectedEvents.slice().reverse() as event}
									<div class="border-l border-gray-800 pl-3">
										<div class="flex items-center gap-2">
											<span class="text-[10px] font-semibold uppercase text-guild-400">{event.event_type}</span>
											<span class="text-[11px] text-gray-600">{event.timestamp}</span>
										</div>
										<p class="mt-1 text-xs leading-5 text-gray-300">{event.message}</p>
									</div>
								{:else}
									<p class="text-sm text-gray-600">No events recorded.</p>
								{/each}
							</div>
						</div>
					</div>
				</section>
			{/if}
		</div>
	{/if}
</div>
