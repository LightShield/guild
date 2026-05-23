<script>
	import { onMount } from 'svelte';
	import { fetchTasks, fetchAgents, fetchLearnings } from '$lib/api.js';
	import { tasks, agents, learnings } from '$lib/stores.js';

	let loading = $state(true);
	let copiedMap = $state({});
	function copyText(key, text) {
		navigator.clipboard.writeText(text ?? '');
		copiedMap = { ...copiedMap, [key]: true };
		setTimeout(() => { copiedMap = { ...copiedMap, [key]: false }; }, 1500);
	}

	onMount(async () => {
		try {
			const [t, a, l] = await Promise.all([
				fetchTasks(),
				fetchAgents(),
				fetchLearnings(),
			]);
			$tasks = t; $agents = a; $learnings = l;
		} finally {
			loading = false;
		}
	});

	// === Derived metrics ===
	const totalTasks = $derived($tasks.length);
	const completedTasks = $derived($tasks.filter(t => t.status === 'completed').length);
	const failedTasks = $derived($tasks.filter(t => t.status === 'failed').length);
	const runningTasks = $derived($tasks.filter(t => t.status === 'running').length);
	const successRate = $derived(totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0);

	const agentStats = $derived.by(() => {
		return $agents.map(agent => {
			const agentTasks = $tasks.filter(t => t.assigned_agent === agent.block_name || t.assigned_agent === agent.agent_id);
			const completed = agentTasks.filter(t => t.status === 'completed').length;
			const failed = agentTasks.filter(t => t.status === 'failed').length;
			const total = agentTasks.length;
			const rate = total > 0 ? Math.round((completed / total) * 100) : 0;
			const tokens = (agent.token_input || 0) + (agent.token_output || 0);
			return { ...agent, completed, failed, total, rate, tokens };
		}).sort((a, b) => b.completed - a.completed || b.rate - a.rate);
	});

	// Task velocity: last 7 days
	const velocityData = $derived.by(() => {
		const days = [];
		for (let i = 6; i >= 0; i--) {
			const d = new Date();
			d.setDate(d.getDate() - i);
			const dateStr = d.toISOString().slice(0, 10);
			const dayTasks = $tasks.filter(t => (t.created_at || '').startsWith(dateStr));
			const completed = dayTasks.filter(t => t.status === 'completed').length;
			const failed = dayTasks.filter(t => t.status === 'failed').length;
			const label = i === 0 ? 'Today' : d.toLocaleDateString('en', { weekday: 'short' });
			days.push({ label, total: dayTasks.length, completed, failed });
		}
		return days;
	});

	const maxDayCount = $derived(Math.max(1, ...velocityData.map(d => d.total)));

	// Top failure agents
	const failureAgents = $derived(
		agentStats.filter(a => a.failed > 0).sort((a, b) => b.failed - a.failed).slice(0, 3)
	);

	// Recent learnings
	const recentLearnings = $derived([...$learnings].slice(-5).reverse());

	function successColor(rate) {
		if (rate >= 80) return '#4ade80';
		if (rate >= 60) return '#fbbf24';
		return '#f87171';
	}

	function barColor(day) {
		if (day.total === 0) return 'var(--border-default)';
		if (day.failed > day.completed) return '#f87171';
		if (day.failed > 0) return '#a78bfa';
		return '#60a5fa';
	}
</script>

<svelte:head><title>Guild — Intelligence</title></svelte:head>

<div class="page animate-fade-in">
	<!-- Header -->
	<div class="page-header">
		<div>
			<div class="label-xs prompt-label" style="margin-bottom: 0.4rem">observatory</div>
			<h1 class="page-title">Intelligence</h1>
		</div>
		<div class="header-sub">System insights · {new Date().toLocaleDateString('en', { weekday: 'long', month: 'short', day: 'numeric' })}</div>
	</div>

	{#if loading}
		<div class="loading-state"><span class="running-dot"></span><span>Analyzing system...</span></div>
	{:else}
		<!-- KPI strip -->
		<div class="kpi-strip">
			<div class="kpi-card" style="--kpi-color: #60a5fa">
				<div class="kpi-label">Total Tasks</div>
				<div class="kpi-value" style="color: #60a5fa">{totalTasks}</div>
			</div>
			<div class="kpi-card" style="--kpi-color: {successColor(successRate)}">
				<div class="kpi-label">Success Rate</div>
				<div class="kpi-value" style="color: {successColor(successRate)}">{successRate}%</div>
				<div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: {successRate}%; background: {successColor(successRate)}"></div></div>
			</div>
			<div class="kpi-card {runningTasks > 0 ? 'kpi-card--live' : ''}" style="--kpi-color: #4ade80">
				<div class="kpi-label">Running Now</div>
				<div class="kpi-value" style="color: #4ade80; {runningTasks > 0 ? 'text-shadow: 0 0 20px rgba(74,222,128,0.7)' : ''}">{runningTasks}</div>
			</div>
			<div class="kpi-card" style="--kpi-color: #2dd4bf">
				<div class="kpi-label">Knowledge</div>
				<div class="kpi-value" style="color: #2dd4bf">{$learnings.length}</div>
			</div>
			<div class="kpi-card" style="--kpi-color: #f87171">
				<div class="kpi-label">Failures</div>
				<div class="kpi-value" style="color: #f87171">{failedTasks}</div>
			</div>
			<div class="kpi-card" style="--kpi-color: #a78bfa">
				<div class="kpi-label">Agents</div>
				<div class="kpi-value" style="color: #a78bfa">{$agents.length}</div>
			</div>
		</div>

		<div class="intel-grid">
			<!-- Left column -->
			<div class="intel-col">
				<!-- Task velocity -->
				<div class="panel intel-panel">
					<div class="panel-head-row">
						<div class="label-xs prompt-label">velocity</div>
						<div class="panel-head-title">7-Day Task Volume</div>
					</div>
					<div class="velocity-chart">
						{#each velocityData as day}
							<div class="vel-col">
								<div class="vel-bar-wrap">
									<div class="vel-bar" style="height: {Math.max(4, (day.total / maxDayCount) * 100)}%; background: {barColor(day)}; box-shadow: {day.total > 0 ? `0 0 8px ${barColor(day)}55` : 'none'}">
									</div>
								</div>
								<div class="vel-count" style="color: {day.total > 0 ? 'var(--text-secondary)' : 'var(--text-tertiary)'}">{day.total}</div>
								<div class="vel-label">{day.label}</div>
							</div>
						{/each}
					</div>
				</div>

				<!-- Agent leaderboard -->
				<div class="panel intel-panel">
					<div class="panel-head-row">
						<div class="label-xs prompt-label">fleet</div>
						<div class="panel-head-title">Agent Leaderboard</div>
					</div>
					{#if agentStats.length === 0}
						<div class="empty-intel">No agents registered yet.</div>
					{:else}
						<div class="leaderboard">
							{#each agentStats.slice(0, 8) as agent, i}
								{@const rankColors = ['#fbbf24', '#94a3b8', '#fb923c', 'var(--text-tertiary)']}
								{@const rankColor = rankColors[Math.min(i, 3)]}
								<div class="agent-row">
									<div class="rank-num" style="color: {rankColor}">{i + 1}</div>
									<div class="agent-row-info">
										<div class="agent-row-name">{agent.block_name}</div>
										<div class="agent-row-bar-bg">
											<div class="agent-row-bar" style="width: {agent.rate}%; background: {agent.rate >= 80 ? '#4ade80' : agent.rate >= 50 ? '#fbbf24' : '#f87171'}"></div>
										</div>
									</div>
									<div class="agent-row-stats">
										<span style="color: #4ade80">{agent.completed}✓</span>
										{#if agent.failed > 0}<span style="color: #f87171"> {agent.failed}✗</span>{/if}
									</div>
									<div class="agent-row-rate" style="color: {agent.rate >= 80 ? '#4ade80' : agent.rate >= 50 ? '#fbbf24' : '#f87171'}">{agent.total > 0 ? agent.rate + '%' : '—'}</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>

			<!-- Right column -->
			<div class="intel-col">
				<!-- Failure patterns -->
				{#if failureAgents.length > 0}
					<div class="panel intel-panel intel-panel--warn">
						<div class="panel-head-row">
							<div class="label-xs" style="color: #f87171; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500">⚠ failure patterns</div>
						</div>
						<div class="failure-list">
							{#each failureAgents as agent}
								<div class="failure-row">
									<div class="failure-name">{agent.block_name}</div>
									<div class="failure-bar-bg">
										<div class="failure-bar" style="width: {(agent.failed / Math.max(...failureAgents.map(a=>a.failed))) * 100}%"></div>
									</div>
									<div class="failure-count">{agent.failed} failed</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Knowledge feed -->
				<div class="panel intel-panel">
					<div class="panel-head-row">
						<div class="label-xs prompt-label">knowledge</div>
						<div class="panel-head-title">Recent Learnings</div>
					</div>
					{#if recentLearnings.length === 0}
						<div class="empty-intel">No learnings recorded yet.</div>
					{:else}
						<div class="learning-list">
							{#each recentLearnings as learning, i}
								{@const colors = ['#2dd4bf', '#a78bfa', '#60a5fa', '#4ade80', '#fb923c']}
								<div class="learning-card copyable-block" style="border-left-color: {colors[i % colors.length]}">
									<button class="copy-btn" onclick={() => copyText(String(i), learning.content || learning.text || learning.learning || JSON.stringify(learning))}>
										{copiedMap[String(i)] ? '✓ Copied' : 'Copy'}
									</button>
									<p class="learning-text">{learning.content || learning.text || learning.learning || JSON.stringify(learning)}</p>
									{#if learning.created_at || learning.timestamp}
										<div class="learning-time">{learning.created_at || learning.timestamp}</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Quick stats -->
				<div class="panel intel-panel">
					<div class="panel-head-row">
						<div class="label-xs prompt-label">breakdown</div>
						<div class="panel-head-title">Task Status Mix</div>
					</div>
					<div class="status-mix">
						{#each [
							{ label: 'Completed', count: completedTasks, color: '#60a5fa' },
							{ label: 'Running', count: runningTasks, color: '#4ade80' },
							{ label: 'Failed', count: failedTasks, color: '#f87171' },
							{ label: 'Pending', count: $tasks.filter(t=>t.status==='pending').length, color: '#94a3b8' },
							{ label: 'Killed', count: $tasks.filter(t=>t.status==='killed').length, color: '#fbbf24' },
						] as s}
							{#if s.count > 0 || s.label === 'Completed'}
								<div class="mix-row">
									<div class="mix-label" style="color: {s.color}">{s.label}</div>
									<div class="mix-bar-bg">
										<div class="mix-bar" style="width: {totalTasks > 0 ? (s.count/totalTasks*100) : 0}%; background: {s.color}; box-shadow: 0 0 6px {s.color}55"></div>
									</div>
									<div class="mix-count" style="color: {s.color}">{s.count}</div>
								</div>
							{/if}
						{/each}
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.page { display: flex; flex-direction: column; gap: 1.5rem; }
	.page-header { display: flex; align-items: flex-end; justify-content: space-between; }
	.page-title {
		font-size: 1.125rem; font-weight: 700;
		background: linear-gradient(90deg, var(--text-primary) 40%, #60a5fa 70%, #a78bfa);
		-webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
	}
	.header-sub { font-size: 0.72rem; color: var(--text-tertiary); }
	.loading-state { display: flex; align-items: center; gap: 0.625rem; font-size: 0.78rem; color: var(--text-secondary); }

	.kpi-strip {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 0.625rem;
	}
	.kpi-card {
		background: var(--bg-surface);
		border: 1px solid var(--border-default);
		border-radius: 0.2rem;
		padding: 0.875rem 1rem;
		display: flex; flex-direction: column; gap: 0.375rem;
		position: relative; overflow: hidden;
		transition: border-color 0.2s;
	}
	.kpi-card::before {
		content: '';
		position: absolute; top: 0; left: 0; right: 0; height: 2px;
		background: var(--kpi-color, var(--accent));
		opacity: 0.7;
	}
	.kpi-card--live { border-color: rgba(74, 222, 128, 0.4); box-shadow: 0 0 16px rgba(74,222,128,0.08); }
	.kpi-label { font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-tertiary); }
	.kpi-value { font-size: 1.75rem; font-weight: 700; line-height: 1; margin-top: 0.25rem; }
	.kpi-bar-bg { height: 2px; background: var(--border-subtle); border-radius: 1px; margin-top: 0.25rem; }
	.kpi-bar-fill { height: 100%; border-radius: 1px; transition: width 0.6s ease; }

	.intel-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
		align-items: start;
	}
	.intel-col { display: flex; flex-direction: column; gap: 1rem; }

	.intel-panel { overflow: hidden; }
	.intel-panel--warn { border-color: rgba(248,113,113,0.25); background: rgba(248,113,113,0.03); }

	.panel-head-row {
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border-subtle);
		display: flex; flex-direction: column; gap: 0.2rem;
	}
	.panel-head-title { font-size: 0.82rem; font-weight: 600; color: var(--text-primary); }

	/* Velocity chart */
	.velocity-chart {
		display: flex; gap: 0.5rem; align-items: flex-end;
		padding: 1rem; height: 10rem;
	}
	.vel-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 0.25rem; height: 100%; }
	.vel-bar-wrap { flex: 1; display: flex; align-items: flex-end; width: 100%; }
	.vel-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 4px; transition: height 0.4s ease; }
	.vel-count { font-size: 0.62rem; color: var(--text-secondary); }
	.vel-label { font-size: 0.6rem; color: var(--text-tertiary); white-space: nowrap; }

	/* Leaderboard */
	.leaderboard { padding: 0.5rem 0; }
	.agent-row {
		display: grid; grid-template-columns: 1.5rem 1fr auto auto;
		gap: 0.625rem; align-items: center;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--border-subtle);
	}
	.agent-row:last-child { border-bottom: none; }
	.rank-num { font-size: 0.72rem; font-weight: 700; text-align: center; }
	.agent-row-info { min-width: 0; }
	.agent-row-name { font-size: 0.78rem; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.agent-row-bar-bg { height: 3px; background: var(--border-subtle); border-radius: 2px; margin-top: 0.3rem; }
	.agent-row-bar { height: 100%; border-radius: 2px; transition: width 0.5s ease; }
	.agent-row-stats { font-size: 0.68rem; white-space: nowrap; }
	.agent-row-rate { font-size: 0.75rem; font-weight: 600; min-width: 2.5rem; text-align: right; }

	/* Failure patterns */
	.failure-list { padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.625rem; }
	.failure-row { display: grid; grid-template-columns: 1fr auto auto; gap: 0.625rem; align-items: center; }
	.failure-name { font-size: 0.75rem; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.failure-bar-bg { height: 4px; background: var(--border-subtle); border-radius: 2px; width: 80px; }
	.failure-bar { height: 100%; background: #f87171; border-radius: 2px; box-shadow: 0 0 4px rgba(248,113,113,0.4); }
	.failure-count { font-size: 0.68rem; color: #f87171; white-space: nowrap; }

	/* Knowledge */
	.learning-list { padding: 0.75rem; display: flex; flex-direction: column; gap: 0.5rem; }
	.learning-card {
		border-left: 3px solid; padding: 0.625rem 0.75rem;
		background: var(--bg-elevated); border-radius: 0 0.15rem 0.15rem 0;
		border-top: 1px solid var(--border-subtle);
		border-right: 1px solid var(--border-subtle);
		border-bottom: 1px solid var(--border-subtle);
	}
	.learning-text { font-size: 0.75rem; color: var(--text-primary); line-height: 1.4; }
	.learning-time { font-size: 0.62rem; color: var(--text-tertiary); margin-top: 0.25rem; }

	/* Status mix */
	.status-mix { padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
	.mix-row { display: grid; grid-template-columns: 5.5rem 1fr 2.5rem; gap: 0.625rem; align-items: center; }
	.mix-label { font-size: 0.68rem; font-weight: 500; letter-spacing: 0.05em; }
	.mix-bar-bg { height: 5px; background: var(--border-subtle); border-radius: 3px; }
	.mix-bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
	.mix-count { font-size: 0.72rem; font-weight: 600; text-align: right; }

	.empty-intel { padding: 1.5rem; font-size: 0.78rem; color: var(--text-secondary); text-align: center; }
</style>
