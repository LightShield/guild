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
	$: pendingTasks = $tasks.filter(t => t.status === 'pending').length;
	$: totalAgents = $agents.length;
	$: activeAgents = $agents.filter(a => a.status === 'running').length;
	$: learningsCount = $learnings.length;
</script>

<svelte:head>
	<title>Guild — Dashboard</title>
</svelte:head>

<div class="page animate-fade-in">

	<!-- Header -->
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">system</div>
			<h1 class="page-title">Dashboard</h1>
		</div>
		{#if !loading && runningTasks > 0}
			<div class="live-badge">
				<span class="running-dot"></span>
				<span>{runningTasks} running</span>
			</div>
		{/if}
	</div>

	{#if loading}
		<div class="loading-state">
			<span class="running-dot"></span>
			<span>Loading system state...</span>
		</div>
	{:else}
		<!-- Stats -->
		<div class="stats-grid">
			<div class="stat-card {runningTasks > 0 ? 'stat-card--running' : ''}">
				{#if runningTasks > 0}
					<div class="stat-card-glow stat-card-glow--green"></div>
				{/if}
				<div class="label-xs">Running</div>
				<div class="stat-number" style="color: {runningTasks > 0 ? '#4ade80' : 'var(--text-primary)'}; {runningTasks > 0 ? 'text-shadow: 0 0 30px rgba(74,222,128,0.7), 0 0 60px rgba(74,222,128,0.3)' : ''}">
					{runningTasks}
				</div>
				<div class="stat-sub">
					{#if pendingTasks > 0}<span>{pendingTasks} queued</span>{:else}<span>active tasks</span>{/if}
				</div>
				{#if runningTasks > 0}
					<div class="stat-card-line stat-card-line--green"></div>
				{:else}
					<div class="stat-card-line stat-card-line--dim"></div>
				{/if}
			</div>

			<div class="stat-card">
				<div class="stat-card-glow stat-card-glow--blue"></div>
				<div class="label-xs">Agents</div>
				<div class="stat-number" style="color: var(--accent)">{totalAgents}</div>
				<div class="stat-sub">
					{#if activeAgents > 0}<span>{activeAgents} live</span>{:else}<span>registered</span>{/if}
				</div>
				<div class="stat-card-line stat-card-line--blue"></div>
			</div>

			<div class="stat-card">
				<div class="label-xs">Knowledge</div>
				<div class="stat-number" style="color: #fbbf24">{learningsCount}</div>
				<div class="stat-sub"><span>learnings</span></div>
				<div class="stat-card-line" style="background: linear-gradient(90deg, #fbbf24, transparent); opacity: 0.35"></div>
			</div>
		</div>

		<!-- Recent Tasks -->
		<div class="panel" style="overflow: hidden">
			<div class="panel-header">
				<div>
					<div class="label-xs prompt-label" style="margin-bottom: 0.3rem">activity</div>
					<div class="panel-title">Recent Tasks</div>
				</div>
				<a href="/tasks" class="link-accent" style="font-size: 0.72rem">View all →</a>
			</div>

			{#if $tasks.length === 0}
				<div class="empty-state">
					<p>No tasks yet.</p>
					<p class="empty-state-sub">Create one to get started.</p>
				</div>
			{:else}
				<div class="task-list">
					{#each $tasks.slice(0, 8) as task}
						<div class="task-row row-hover">
							<div class="task-row-indicator">
								{#if task.status === 'running'}
									<span class="running-dot"></span>
								{:else}
									<span class="status-dot status-dot--{task.status}"></span>
								{/if}
							</div>
							<p class="task-row-desc">{task.description}</p>
							<span class="status-badge status-{task.status}">{task.status}</span>
							<span class="task-row-time">{task.created_at ? new Date(task.created_at).toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Actions -->
		<div class="actions-row">
			<a href="/tasks" class="btn-primary">+ New Task</a>
			<a href="/agents" class="btn-ghost">View Agents</a>
		</div>
	{/if}
</div>

<style>
	.page { display: flex; flex-direction: column; gap: 1.5rem; }

	.page-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		padding-bottom: 0.25rem;
	}
	.page-title {
		font-size: 1.125rem;
		font-weight: 700;
		letter-spacing: 0.02em;
		background: linear-gradient(90deg, var(--text-primary) 60%, var(--text-secondary));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}

	.live-badge {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem 0.75rem;
		background: rgba(52, 211, 153, 0.08);
		border: 1px solid rgba(52, 211, 153, 0.2);
		border-radius: 0.15rem;
		font-size: 0.72rem;
		font-weight: 500;
		color: var(--running);
	}

	.loading-state {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		font-size: 0.8rem;
		color: var(--text-secondary);
		padding: 1rem 0;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.75rem;
	}

	.stat-card {
		position: relative;
		overflow: hidden;
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		padding: 1.25rem 1.25rem 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
		transition: border-color 0.2s;
	}
	.stat-card--running {
		border-color: rgba(74, 222, 128, 0.4);
		box-shadow: 0 0 20px rgba(74, 222, 128, 0.08);
	}
	.stat-card-glow {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	.stat-card-glow--green {
		background: radial-gradient(ellipse at 0% 100%, rgba(74,222,128,0.22), transparent 55%);
	}
	.stat-card-glow--blue {
		background: radial-gradient(ellipse at 0% 100%, rgba(56,189,248,0.18), transparent 55%);
	}
	.stat-number {
		font-size: 2.5rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1;
		margin-top: 0.5rem;
	}
	.stat-sub {
		font-size: 0.68rem;
		color: var(--text-secondary);
		margin-top: 0.25rem;
	}
	.stat-card-line {
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		height: 1px;
	}
	.stat-card-line--green { background: linear-gradient(90deg, var(--running), transparent); }
	.stat-card-line--blue { background: linear-gradient(90deg, var(--accent), transparent); opacity: 0.4; }
	.stat-card-line--dim { background: linear-gradient(90deg, var(--border-strong), transparent); opacity: 0.3; }

	.panel-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--border-subtle);
	}
	.panel-title {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.empty-state {
		padding: 2.5rem 1.25rem;
		text-align: center;
		font-size: 0.8rem;
		color: var(--text-secondary);
	}
	.empty-state-sub {
		font-size: 0.7rem;
		color: var(--text-tertiary);
		margin-top: 0.25rem;
	}

	.task-list { }
	.task-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.625rem 1.25rem;
		border-bottom: 1px solid var(--border-subtle);
	}
	.task-row:last-child { border-bottom: none; }
	.task-row-indicator { flex-shrink: 0; display: flex; align-items: center; }
	.task-row-desc {
		flex: 1;
		font-size: 0.78rem;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.task-row-time {
		font-size: 0.68rem;
		color: var(--text-secondary);
		flex-shrink: 0;
		white-space: nowrap;
	}

	.status-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
	}
	.status-dot--completed { background: #38bdf8; }
	.status-dot--failed { background: #f87171; }
	.status-dot--killed { background: #fbbf24; }
	.status-dot--pending { background: var(--text-tertiary); }

	.actions-row { display: flex; gap: 0.625rem; }
</style>
