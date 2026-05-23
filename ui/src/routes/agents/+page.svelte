<script>
	import { onMount } from 'svelte';
	import { fetchAgents } from '$lib/api.js';
	import { agents } from '$lib/stores.js';

	let loading = $state(true);
	let activeOnly = $state(false);
	let expandedDescIds = $state(new Set());
	function toggleAgentDesc(id, e) {
		e.stopPropagation();
		const s = new Set(expandedDescIds);
		s.has(id) ? s.delete(id) : s.add(id);
		expandedDescIds = s;
	}

	const orderedAgents = $derived.by(() => {
		const sorted = [...$agents].sort((a, b) => String(b.last_seen || b.created_at || '').localeCompare(String(a.last_seen || a.created_at || '')));
		return activeOnly ? sorted.filter(a => a.status === 'running') : sorted;
	});
	const activeAgents = $derived(orderedAgents.filter((agent) => agent.status === 'running'));
	const historicalAgents = $derived(orderedAgents.filter((agent) => agent.status !== 'running'));

	onMount(async () => {
		try {
			$agents = await fetchAgents();
		} catch (e) {
			console.error('Failed to load agents:', e);
		} finally {
			loading = false;
		}
	});

	function statusClass(status) {
		if (status === 'running') return 'bg-green-950/70 text-green-300 border-green-900';
		if (status === 'completed') return 'bg-sky-950/70 text-sky-300 border-sky-900';
		if (status === 'failed') return 'bg-red-950/70 text-red-300 border-red-900';
		return 'bg-gray-800 text-gray-300 border-gray-700';
	}

	function taskLabel(agent) {
		const task = agent.parent_task || agent.task;
		if (!task) return 'Legacy row: no task link stored';
		const label = task.description || task.task_id;
		if (task.status === 'killed') return `[stopped] ${label}`;
		if (task.status === 'failed') return `[failed] ${label}`;
		return label;
	}

	function originLabel(agent) {
		if (agent.parent_task) return `workflow ${agent.parent_task.assigned_agent || agent.parent_task.task_id?.slice(0, 8)}`;
		if (agent.task) return `direct ${agent.task.task_id?.slice(0, 8)}`;
		return 'legacy';
	}

	function originHref(agent) {
		if (agent.parent_task) return `/workflows?execution=${encodeURIComponent(agent.parent_task.task_id)}`;
		if (agent.task) return `/tasks`;
		return '';
	}
</script>

<svelte:head>
	<title>Guild — Agents</title>
</svelte:head>

<div class="page animate-fade-in">
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">fleet</div>
			<h1 class="page-title">Agents</h1>
		</div>
		<div class="agent-counts">
			<div class="count-chip {activeAgents.length > 0 ? 'count-chip--live' : ''}">
				{#if activeAgents.length > 0}<span class="running-dot"></span>{/if}
				<span class="count-chip-label">Active</span>
				<span class="count-chip-val">{activeAgents.length}</span>
			</div>
			<div class="count-chip">
				<span class="count-chip-label">History</span>
				<span class="count-chip-val">{historicalAgents.length}</span>
			</div>
			<button
				type="button"
				onclick={() => activeOnly = !activeOnly}
				class="toggle-active-btn {activeOnly ? 'toggle-active-btn--on' : ''}"
			>
				{activeOnly ? '● Active only' : '○ All agents'}
			</button>
		</div>
	</div>

	{#if loading}
		<div class="loading-state"><span class="running-dot"></span><span>Loading agents...</span></div>
	{:else if orderedAgents.length === 0}
		<div class="panel empty-panel">
			<p>No agents registered yet.</p>
			<p class="empty-sub">Agents are created when tasks are assigned.</p>
		</div>
	{:else}
		<div class="panel" style="overflow: hidden">
			<table class="data-table">
				<thead>
					<tr class="table-head-row">
						<th class="th">Agent</th>
						<th class="th">Status</th>
						<th class="th">Origin</th>
						<th class="th" style="width: 99%">Task</th>
						<th class="th th--right">Tokens</th>
						<th class="th">Last seen</th>
					</tr>
				</thead>
				<tbody>
					{#each orderedAgents as agent}
						<tr class="data-row row-hover row-{agent.status}">
							<td class="td">
								<p class="agent-name">{agent.block_name}</p>
								<p class="agent-id">{agent.agent_id}</p>
							</td>
							<td class="td">
								<div class="status-cell">
									{#if agent.status === 'running'}<span class="running-dot"></span>{/if}
									<span class="status-badge status-{agent.status}">{agent.status}</span>
								</div>
							</td>
							<td class="td">
								{#if originHref(agent)}
									<a href={originHref(agent)} class="link-accent" style="font-size: 0.72rem">{originLabel(agent)}</a>
								{:else}
									<span class="td--dim">{originLabel(agent)}</span>
								{/if}
							</td>
							<td class="td td--desc">
								<p class="expandable-text {expandedDescIds.has(agent.agent_id) ? 'expandable-text--open' : ''}" style="font-size: 0.78rem" onclick={(e) => toggleAgentDesc(agent.agent_id, e)}>{taskLabel(agent)}</p>
								{#if agent.parent_task}
									<p class="agent-flow">flow {agent.parent_task.task_id?.slice(0, 8)}</p>
								{:else if agent.task}
									<p class="agent-flow">task {agent.task.task_id?.slice(0, 8)}</p>
								{/if}
							</td>
							<td class="td td--right">
								<p class="token-in">{(agent.token_input || 0).toLocaleString()} in</p>
								<p class="token-out">{(agent.token_output || 0).toLocaleString()} out</p>
							</td>
							<td class="td td--dim td--mono" style="font-size: 0.68rem; white-space: nowrap">
								{agent.last_seen || agent.created_at}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
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

	.loading-state { display: flex; align-items: center; gap: 0.625rem; font-size: 0.78rem; color: var(--text-secondary); }

	.agent-counts { display: flex; gap: 0.5rem; }
	.count-chip {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.35rem 0.75rem;
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		font-size: 0.72rem;
	}
	.count-chip--live { border-color: rgba(52,211,153,0.25); background: rgba(52,211,153,0.05); }
	.count-chip-label { color: var(--text-secondary); }
	.count-chip-val { font-weight: 600; color: var(--text-primary); }

	.empty-panel { padding: 3rem; text-align: center; font-size: 0.8rem; color: var(--text-secondary); }
	.empty-sub { font-size: 0.72rem; color: var(--text-tertiary); margin-top: 0.375rem; }

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

	.data-row { border-bottom: 1px solid var(--border-subtle); }
	.td { padding: 0.625rem 1rem; font-size: 0.78rem; color: var(--text-primary); vertical-align: middle; }
	.td--dim { color: var(--text-secondary); font-size: 0.72rem; }
	.td--mono { font-family: inherit; }
	.td--desc { max-width: 0; }
	.td--right { text-align: right; }

	.status-cell { display: flex; align-items: center; gap: 0.4rem; }

	.agent-name { font-weight: 600; font-size: 0.8rem; color: var(--text-primary); }
	.agent-id { font-size: 0.68rem; color: var(--text-tertiary); margin-top: 0.1rem; }
	.agent-flow { font-size: 0.68rem; color: var(--text-tertiary); margin-top: 0.15rem; }

	.token-in { font-size: 0.75rem; color: var(--text-primary); text-align: right; }
	.token-out { font-size: 0.65rem; color: var(--text-secondary); text-align: right; }

	.toggle-active-btn {
		display: flex; align-items: center; gap: 0.375rem;
		padding: 0.35rem 0.75rem;
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.15rem;
		font-size: 0.72rem; font-weight: 500;
		color: var(--text-secondary);
		cursor: pointer;
		transition: all 0.15s;
		font-family: inherit;
		letter-spacing: 0.04em;
	}
	.toggle-active-btn:hover {
		border-color: rgba(52,211,153,0.35);
		color: var(--text-primary);
	}
	.toggle-active-btn--on {
		border-color: rgba(52,211,153,0.4);
		background: rgba(52,211,153,0.08);
		color: #34d399;
		box-shadow: 0 0 10px rgba(52,211,153,0.1);
	}
</style>
