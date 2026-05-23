<script>
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { fetchTasks, fetchWorkflow, fetchWorkflows } from '$lib/api.js';
	import { taskEvents, tasks } from '$lib/stores.js';

	let loading = $state(true);
	let selectedWorkflowId = $state('');
	let workflowRecords = $state([]);
	let selectedRecord = $state(null);
	let fullEvents = $state([]);
	let childEvents = $state([]);
	let copied = $state('');
	let apiUnavailable = $state(false);

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
		await loadWorkflows();
		const requestedExecution = page.url.searchParams.get('execution');
		if (requestedExecution) {
			await selectWorkflow(requestedExecution);
		}
	});

	async function loadWorkflows() {
		loading = true;
		try {
			const [records, loadedTasks] = await Promise.all([
				fetchWorkflows().catch((error) => {
					apiUnavailable = true;
					console.warn('Workflow API unavailable; falling back to task/event data:', error);
					return [];
				}),
				fetchTasks()
			]);
			workflowRecords = records;
			$tasks = loadedTasks;
			if (records.length) apiUnavailable = false;
		} finally {
			loading = false;
		}
	}

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
		if (!taskId || selectedWorkflowId === taskId) return;
		selectedWorkflowId = taskId;
		selectedRecord = null;
		fullEvents = [];
		childEvents = [];
		copied = '';
		try {
			selectedRecord = await fetchWorkflow(taskId);
			fullEvents = selectedRecord.events || [];
			childEvents = selectedRecord.child_events || [];
			apiUnavailable = false;
		} catch (error) {
			apiUnavailable = true;
			console.warn('Workflow detail API unavailable; using live task/event data:', error);
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

<div class="page animate-fade-in">
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">orchestration</div>
			<h1 class="page-title">Workflows</h1>
		</div>
		<div class="stat-row">
			<div class="stat-chip">
				<div class="label-xs">Active</div>
				<div class="stat-num" style="color: var(--running)">{activeWorkflows.length}</div>
			</div>
			<div class="stat-chip">
				<div class="label-xs">History</div>
				<div class="stat-num">{pastWorkflows.length}</div>
			</div>
			<div class="stat-chip">
				<div class="label-xs">Blocks</div>
				<div class="stat-num" style="color: var(--accent)">{selectedBlockRuns.length}</div>
			</div>
		</div>
	</div>

	{#if apiUnavailable}
		<div class="notice-bar">
			<p>Workflow API detail fetch failed. Showing live fallback data.</p>
			<button type="button" onclick={loadWorkflows} class="btn-ghost" style="font-size: 0.65rem; padding: 0.3rem 0.625rem">Retry</button>
		</div>
	{/if}

	{#if loading}
		<div class="loading-state"><span class="running-dot"></span><span>Loading workflows...</span></div>
	{:else if workflowTasks.length === 0}
		<div class="panel empty-panel">No workflow runs yet.</div>
	{:else}
		<div class="wf-layout">
			<aside class="wf-sidebar">
				<section>
					<div class="label-xs prompt-label" style="margin-bottom: 0.625rem">active</div>
					<div class="wf-list">
						{#each activeWorkflows as workflow}
							<button
								type="button"
								onclick={() => selectWorkflow(executionId(workflow))}
								class="wf-item {executionId(selectedWorkflow) === executionId(workflow) ? 'wf-item--active' : ''}"
							>
								<div class="wf-item-top">
									<span class="running-dot"></span>
									<p class="wf-name">{workflow.assigned_agent}</p>
									<span class="status-badge status-{workflow.status}">{workflow.status}</span>
								</div>
								<p class="wf-desc">{workflow.description}</p>
								<p class="wf-id">exec {shortId(executionId(workflow))}</p>
							</button>
						{:else}
							<div class="empty-state">No active workflows.</div>
						{/each}
					</div>
				</section>

				<section style="margin-top: 1.25rem">
					<div class="label-xs prompt-label" style="margin-bottom: 0.625rem">completed / failed</div>
					<div class="wf-list wf-list--scroll">
						{#each pastWorkflows as workflow}
							<button
								type="button"
								onclick={() => selectWorkflow(executionId(workflow))}
								class="wf-item {executionId(selectedWorkflow) === executionId(workflow) ? 'wf-item--active' : ''}"
							>
								<div class="wf-item-top">
									<span class="status-dot status-dot--{workflow.status}"></span>
									<p class="wf-name">{workflow.assigned_agent}</p>
									<span class="status-badge status-{workflow.status}">{workflow.status}</span>
								</div>
								<p class="wf-desc">{workflow.description}</p>
								<p class="wf-id">exec {shortId(executionId(workflow))}</p>
								<p class="wf-time">{workflow.completed_at || workflow.created_at}</p>
							</button>
						{/each}
					</div>
				</section>
			</aside>

			{#if selectedWorkflow}
				<section class="wf-detail">
					<div class="panel wf-detail-header">
						<div class="wf-detail-title-row">
							<div class="wf-detail-title-left">
								<div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap">
									<h2 class="detail-title">{selectedWorkflow.assigned_agent}</h2>
									<span class="status-badge status-{selectedWorkflow.status}">{selectedWorkflow.status}</span>
								</div>
								<p class="detail-desc">{selectedWorkflow.description}</p>
								<div class="detail-id-row">
									<span class="wf-id-full">exec={executionId(selectedWorkflow)}</span>
									<button type="button" onclick={() => copyText('execution', executionId(selectedWorkflow))} class="btn-ghost" style="font-size: 0.65rem; padding: 0.18rem 0.5rem">
										{copied === 'execution' ? 'Copied' : 'Copy ID'}
									</button>
								</div>
							</div>
							<button type="button" onclick={() => copyText('workflow', workflowOutput(selectedWorkflow))} class="btn-ghost" style="align-self: flex-start; flex-shrink: 0">
								{copied === 'workflow' ? 'Copied' : 'Copy output'}
							</button>
						</div>
					</div>

					<div class="wf-detail-body">
						<div class="wf-main-col">
							<div class="panel" style="padding: 1rem">
								<div class="section-head">
									<div class="label-xs prompt-label">output</div>
									<span class="wf-time">{selectedWorkflow.completed_at || selectedWorkflow.created_at}</span>
								</div>
								<pre class="output-pre">{workflowOutput(selectedWorkflow) || 'No output written yet.'}</pre>
							</div>

							<div class="panel" style="padding: 1rem">
								<div class="label-xs prompt-label" style="margin-bottom: 0.75rem">block runs</div>
								<div class="block-list">
									{#each selectedBlockRuns as block}
										<div class="block-run">
											<div class="block-run-head">
												<div>
													<p class="block-name">{block.blockName}</p>
													<p class="block-id">{block.agentId}</p>
												</div>
												<span class="status-badge status-{block.status}">{block.status}</span>
											</div>
											{#if block.result}
												<pre class="block-output">{block.result}</pre>
												<button
													type="button"
													onclick={() => copyText(block.agentId, block.result)}
													class="link-accent"
													style="font-size: 0.68rem; margin-top: 0.375rem; background: none; border: none; cursor: pointer; padding: 0"
												>
													{copied === block.agentId ? 'Copied' : 'Copy output'}
												</button>
											{/if}
										</div>
									{:else}
										<p class="empty-state">No block agents recorded.</p>
									{/each}
								</div>
							</div>
						</div>

						<div class="panel wf-timeline-col">
							<div class="label-xs prompt-label" style="margin-bottom: 0.75rem">timeline</div>
							<div class="timeline-list">
								{#each selectedEvents.slice().reverse() as event}
									<div class="t-event">
										<div class="t-event-head">
											<span class="t-event-type">{event.event_type}</span>
											<span class="t-event-time">{event.timestamp}</span>
										</div>
										<p class="t-event-msg">{event.message}</p>
									</div>
								{:else}
									<p class="empty-state">No events recorded.</p>
								{/each}
							</div>
						</div>
					</div>
				</section>
			{/if}
		</div>
	{/if}
</div>

<style>
	.page { display: flex; flex-direction: column; gap: 1.25rem; }
	.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
	.page-title {
		font-size: 1.125rem;
		font-weight: 700;
		background: linear-gradient(90deg, var(--text-primary) 60%, var(--text-secondary));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}

	.stat-row { display: flex; gap: 0.5rem; }
	.stat-chip {
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		padding: 0.625rem 0.875rem;
		min-width: 4.5rem;
		text-align: right;
	}
	.stat-num { font-size: 1.5rem; font-weight: 700; color: var(--text-primary); line-height: 1; margin-top: 0.25rem; }

	.loading-state { display: flex; align-items: center; gap: 0.625rem; font-size: 0.78rem; color: var(--text-secondary); }
	.empty-panel { padding: 3rem; text-align: center; font-size: 0.8rem; color: var(--text-secondary); }

	.notice-bar {
		display: flex; align-items: center; justify-content: space-between; gap: 1rem;
		padding: 0.625rem 0.875rem;
		background: rgba(251, 191, 36, 0.06);
		border: 1px solid rgba(251, 191, 36, 0.2);
		border-radius: 0.15rem;
		font-size: 0.78rem;
		color: #fbbf24;
	}

	.wf-layout {
		display: grid;
		grid-template-columns: 260px 1fr;
		gap: 1rem;
		align-items: start;
	}

	.wf-sidebar { display: flex; flex-direction: column; }
	.wf-list { display: flex; flex-direction: column; }
	.wf-list--scroll { max-height: 48vh; overflow-y: auto; }

	.wf-item {
		width: 100%;
		text-align: left;
		padding: 0.625rem 0.75rem;
		border: 1px solid var(--border-subtle);
		border-left: 3px solid transparent;
		border-radius: 0.15rem;
		background: var(--bg-surface);
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		margin-bottom: 0.375rem;
		transition: background 0.1s;
	}
	.wf-item:hover { background: var(--bg-hover); }
	.wf-item--active { border-left-color: var(--accent); background: rgba(56, 189, 248, 0.06); }

	.detail-title {
		font-size: 0.95rem;
		font-weight: 700;
		background: linear-gradient(90deg, var(--text-primary) 60%, var(--text-secondary));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}

	.wf-item-top { display: flex; align-items: center; gap: 0.375rem; }
	.wf-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.wf-desc { font-size: 0.72rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.wf-id { font-size: 0.65rem; color: var(--text-tertiary); }
	.wf-time { font-size: 0.65rem; color: var(--text-tertiary); }

	.status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
	.status-dot--completed { background: var(--accent); }
	.status-dot--failed, .status-dot--killed { background: #f87171; }
	.status-dot--pending { background: var(--text-tertiary); }

	.empty-state { font-size: 0.75rem; color: var(--text-secondary); padding: 0.5rem 0; }

	.wf-detail { display: flex; flex-direction: column; gap: 0.875rem; }
	.wf-detail-header { padding: 0.875rem 1rem; }
	.wf-detail-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
	.wf-detail-title-left { flex: 1; min-width: 0; }
	/* detail-title defined above with gradient */
	.detail-desc { font-size: 0.78rem; color: var(--text-secondary); margin-top: 0.3rem; }
	.detail-id-row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.375rem; flex-wrap: wrap; }
	.wf-id-full { font-size: 0.65rem; color: var(--text-tertiary); word-break: break-all; }

	.wf-detail-body { display: grid; grid-template-columns: 1fr 250px; gap: 0.875rem; align-items: start; }
	.wf-main-col { display: flex; flex-direction: column; gap: 0.875rem; }
	.section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.625rem; }

	.output-pre {
		white-space: pre-wrap; word-break: break-words;
		max-height: 40vh; overflow-y: auto;
		font-size: 0.78rem; line-height: 1.6;
		color: var(--text-primary);
		background: var(--bg-base);
		border: 1px solid var(--border-subtle);
		border-radius: 0.15rem;
		padding: 0.75rem;
		font-family: inherit;
	}

	.block-list { display: flex; flex-direction: column; gap: 0.625rem; }
	.block-run { background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 0.15rem; padding: 0.75rem; }
	.block-run-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; }
	.block-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); }
	.block-id { font-size: 0.65rem; color: var(--text-tertiary); margin-top: 0.1rem; }
	.block-output {
		margin-top: 0.625rem; max-height: 12rem; overflow-y: auto;
		white-space: pre-wrap; word-break: break-words;
		font-size: 0.72rem; line-height: 1.5; color: var(--text-primary);
		background: var(--bg-base); border: 1px solid var(--border-subtle);
		border-radius: 0.15rem; padding: 0.5rem 0.625rem; font-family: inherit;
	}

	.wf-timeline-col { padding: 1rem; position: sticky; top: 0; }
	.timeline-list { display: flex; flex-direction: column; gap: 0.5rem; max-height: 70vh; overflow-y: auto; }
	.t-event { border-left: 2px solid var(--border-default); padding-left: 0.625rem; }
	.t-event-head { display: flex; align-items: center; gap: 0.5rem; }
	.t-event-type { font-size: 0.65rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--accent); }
	.t-event-time { font-size: 0.65rem; color: var(--text-tertiary); }
	.t-event-msg { font-size: 0.72rem; color: var(--text-primary); margin-top: 0.2rem; line-height: 1.4; }
</style>
