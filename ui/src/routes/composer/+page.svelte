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
	<title>Guild — Composer</title>
</svelte:head>

<div class="page animate-fade-in">
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">orchestration</div>
			<h1 class="page-title">Composer</h1>
		</div>
		<div class="header-actions">
			<a href="/composer-studio" class="btn-primary">Open Studio</a>
			<a href="/workflows" class="btn-ghost">Workflows</a>
		</div>
	</div>

	{#if apiNotice}
		<div class="notice-bar">
			<p>{apiNotice}</p>
			<button type="button" onclick={loadComposer} class="btn-ghost" style="font-size: 0.65rem; padding: 0.3rem 0.625rem">Retry</button>
		</div>
	{/if}

	{#if loading}
		<div class="loading-state"><span class="running-dot"></span><span>Loading composer...</span></div>
	{:else}
		<!-- Stats row -->
		<div class="composer-stats">
			<div class="c-stat">
				<div class="label-xs">Saved flows</div>
				<div class="c-stat-num">{teams.length}</div>
			</div>
			<div class="c-stat {activeWorkflows.length > 0 ? 'c-stat--active' : ''}">
				{#if activeWorkflows.length > 0}<span class="running-dot" style="position: absolute; top: 0.875rem; right: 0.875rem"></span>{/if}
				<div class="label-xs">Active</div>
				<div class="c-stat-num" style="color: {activeWorkflows.length > 0 ? 'var(--running)' : 'var(--text-primary)'}">{activeWorkflows.length}</div>
			</div>
			<div class="c-stat">
				<div class="label-xs">Recent runs</div>
				<div class="c-stat-num" style="color: var(--accent)">{recentWorkflows.length}</div>
			</div>
		</div>

		<div class="composer-grid">
			<!-- Saved flows -->
			<section>
				<div class="panel" style="overflow: hidden">
					<div class="panel-head">
						<div>
							<div class="label-xs prompt-label" style="margin-bottom: 0.25rem">flows</div>
							<div class="panel-title">Saved Flows</div>
						</div>
						<a href="/composer-studio" class="link-accent" style="font-size: 0.72rem">New / Edit →</a>
					</div>
					<div class="flow-list">
						{#each teams as team}
							<a href={`/composer-studio?team=${encodeURIComponent(team.name)}`} class="flow-item row-hover">
								<div class="flow-item-row">
									<p class="flow-name">{team.name}</p>
									<span class="flow-open">open →</span>
								</div>
								<p class="flow-meta">{team.blocks?.length || Object.keys(team.blocks || {}).length || 0} blocks</p>
							</a>
						{:else}
							<div class="empty-state">No saved flows yet. Open Studio to create one.</div>
						{/each}
					</div>
				</div>
			</section>

			<!-- Sidebar: active + recent -->
			<aside class="composer-aside">
				<div class="panel" style="overflow: hidden">
					<div class="panel-head">
						<div class="label-xs prompt-label">active</div>
					</div>
					<div class="workflow-list">
						{#each activeWorkflows as workflow}
							<a href={`/workflows?execution=${encodeURIComponent(executionId(workflow))}`} class="wf-item row-hover">
								<div class="wf-item-row">
									<div class="flex items-center gap-1.5">
										<span class="running-dot"></span>
										<p class="wf-name">{workflow.assigned_agent}</p>
									</div>
									<span class="status-badge status-{workflow.status}">{workflow.status}</span>
								</div>
								<p class="wf-desc">{workflow.description}</p>
								<p class="wf-id">exec {shortId(executionId(workflow))}</p>
							</a>
						{:else}
							<div class="empty-state">No active workflows.</div>
						{/each}
					</div>
				</div>

				<div class="panel" style="overflow: hidden">
					<div class="panel-head">
						<div class="label-xs prompt-label">recent</div>
					</div>
					<div class="workflow-list">
						{#each recentWorkflows as workflow}
							<a href={`/workflows?execution=${encodeURIComponent(executionId(workflow))}`} class="wf-item row-hover">
								<div class="wf-item-row">
									<p class="wf-name">{workflow.assigned_agent}</p>
									<span class="status-badge status-{workflow.status}">{workflow.status}</span>
								</div>
								<p class="wf-id">exec {shortId(executionId(workflow))}</p>
							</a>
						{:else}
							<div class="empty-state">No finished workflows yet.</div>
						{/each}
					</div>
				</div>
			</aside>
		</div>
	{/if}
</div>

<style>
	.page { display: flex; flex-direction: column; gap: 1.25rem; }
	.page-header { display: flex; align-items: flex-end; justify-content: space-between; }
	.page-title {
		font-size: 1.125rem;
		font-weight: 700;
		background: linear-gradient(90deg, var(--text-primary) 60%, var(--text-secondary));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}
	.header-actions { display: flex; gap: 0.5rem; }

	.loading-state { display: flex; align-items: center; gap: 0.625rem; font-size: 0.78rem; color: var(--text-secondary); }

	.notice-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.625rem 0.875rem;
		background: rgba(251, 191, 36, 0.06);
		border: 1px solid rgba(251, 191, 36, 0.2);
		border-radius: 0.15rem;
		font-size: 0.78rem;
		color: #fbbf24;
	}

	.composer-stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.625rem;
	}
	.c-stat {
		position: relative;
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		padding: 0.875rem 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}
	.c-stat--active {
		border-color: rgba(52,211,153,0.2);
		background: rgba(52,211,153,0.04);
	}
	.c-stat-num { font-size: 2rem; font-weight: 700; color: var(--text-primary); line-height: 1; margin-top: 0.375rem; }

	.composer-grid {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: 1rem;
		align-items: start;
	}

	.panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border-subtle);
	}
	.panel-title { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); margin-top: 0.15rem; }

	.flow-list { }
	.flow-item {
		display: block;
		padding: 0.625rem 1rem;
		border-bottom: 1px solid var(--border-subtle);
		text-decoration: none;
	}
	.flow-item:last-child { border-bottom: none; }
	.flow-item-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
	.flow-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.flow-open { font-size: 0.65rem; color: var(--text-secondary); white-space: nowrap; }
	.flow-meta { font-size: 0.65rem; color: var(--text-secondary); margin-top: 0.15rem; }

	.empty-state { padding: 1.5rem; text-align: center; font-size: 0.75rem; color: var(--text-secondary); }

	.composer-aside { display: flex; flex-direction: column; gap: 0.75rem; }

	.workflow-list { }
	.wf-item {
		display: block;
		padding: 0.625rem 0.875rem;
		border-bottom: 1px solid var(--border-subtle);
		text-decoration: none;
	}
	.wf-item:last-child { border-bottom: none; }
	.wf-item-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
	.wf-name { font-size: 0.78rem; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.wf-desc { font-size: 0.68rem; color: var(--text-secondary); margin-top: 0.25rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.wf-id { font-size: 0.6rem; color: var(--text-tertiary); margin-top: 0.25rem; }
</style>
