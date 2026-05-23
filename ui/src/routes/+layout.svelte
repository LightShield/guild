<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { connectWebSocket, wsConnected } from '$lib/stores.js';
	import '../app.css';

	let { children } = $props();

	const nav = [
		{ href: '/', label: 'Dashboard', icon: 'dashboard' },
		{ href: '/tasks', label: 'Tasks', icon: 'tasks' },
		{ href: '/workflows', label: 'Workflows', icon: 'workflows' },
		{ href: '/agents', label: 'Agents', icon: 'agents' },
		{ href: '/config', label: 'Config', icon: 'config' },
		{ href: '/composer-studio', label: 'Composer Studio', icon: 'studio' },
		{ href: '/messages', label: 'Messages', icon: 'messages' },
		{ href: '/intelligence', label: 'Intelligence', icon: 'intelligence' },
	];

	let ws = null;
	let collapsed = $state(false);

	onMount(() => {
		ws = connectWebSocket();
		const stored = localStorage.getItem('guild-sidebar-collapsed');
		if (stored === 'true') collapsed = true;
	});

	onDestroy(() => {
		if (ws) ws.close();
	});

	function toggleSidebar() {
		collapsed = !collapsed;
		localStorage.setItem('guild-sidebar-collapsed', String(collapsed));
	}
</script>

{#snippet navIcon(name)}
	{#if name === 'dashboard'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
			<rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
		</svg>
	{:else if name === 'tasks'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
		</svg>
	{:else if name === 'workflows'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
			<line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
		</svg>
	{:else if name === 'agents'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/>
			<path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>
		</svg>
	{:else if name === 'config'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<circle cx="12" cy="12" r="3"/>
			<path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
		</svg>
	{:else if name === 'composer'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<polygon points="12,2 2,7 12,12 22,7"/>
			<polyline points="2,17 12,22 22,17"/>
			<polyline points="2,12 12,17 22,12"/>
		</svg>
	{:else if name === 'studio'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/>
		</svg>
	{:else if name === 'messages'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
		</svg>
	{:else if name === 'intelligence'}
		<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
			<path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"/>
			<path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"/>
		</svg>
	{/if}
{/snippet}

<div class="flex h-screen overflow-hidden">
	<!-- Sidebar -->
	<aside class="sidebar {collapsed ? 'sidebar--collapsed' : 'sidebar--expanded'} flex flex-col shrink-0 transition-all duration-200">

		<!-- Logo -->
		<div class="logo-row">
			{#if !collapsed}
				<div class="logo-text">
					<span class="logo-name">GUILD</span>
					<span class="logo-version">v0.2.0</span>
				</div>
			{:else}
				<span class="logo-collapsed">G</span>
			{/if}
			<button class="collapse-btn" onclick={toggleSidebar} title="{collapsed ? 'Expand' : 'Collapse'} sidebar">
				<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					{#if collapsed}
						<polyline points="9,18 15,12 9,6"/>
					{:else}
						<polyline points="15,18 9,12 15,6"/>
					{/if}
				</svg>
			</button>
		</div>

		<!-- Nav -->
		<nav class="flex-1 py-2 px-1.5 space-y-px overflow-y-auto">
			{#each nav as item}
				{@const isActive = page.url.pathname === item.href || (item.href !== '/' && page.url.pathname.startsWith(`${item.href}/`))}
				<a href={item.href} class="nav-link {isActive ? 'nav-link--active' : ''} {collapsed ? 'nav-link--icon-only' : ''}" data-nav={item.icon} title={collapsed ? item.label : ''}>
					<span class="nav-icon">{@render navIcon(item.icon)}</span>
					{#if !collapsed}
						<span class="nav-label">{item.label}</span>
					{/if}
				</a>
			{/each}
		</nav>

		<!-- WS status -->
		<div class="ws-status {collapsed ? 'ws-status--collapsed' : ''}">
			{#if $wsConnected}
				<span class="running-dot"></span>
			{:else}
				<span class="offline-dot"></span>
			{/if}
			{#if !collapsed}
				<span class="ws-label {$wsConnected ? 'ws-label--live' : 'ws-label--offline'}">
					{$wsConnected ? 'LIVE' : 'OFFLINE'}
				</span>
			{/if}
		</div>
	</aside>

	<!-- Main -->
	<main class="main-content flex-1 overflow-y-auto">
		<div class="main-inner">
			{@render children()}
		</div>
	</main>
</div>

<style>
	.sidebar {
		background: var(--bg-surface);
		border-right: 1px solid var(--border-default);
		box-shadow: 4px 0 24px rgba(4, 6, 20, 0.5);
		position: relative;
	}
	/* subtle indigo glow on right edge */
	.sidebar::after {
		content: '';
		position: absolute;
		top: 0;
		right: -1px;
		width: 1px;
		height: 100%;
		background: linear-gradient(180deg, rgba(96,165,250,0.0) 0%, rgba(96,165,250,0.35) 40%, rgba(167,139,250,0.25) 70%, rgba(96,165,250,0.0) 100%);
		pointer-events: none;
	}
	.sidebar--expanded { width: 14rem; }
	.sidebar--collapsed { width: 3.25rem; }

	.logo-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 0.75rem 0.875rem;
		border-bottom: 1px solid var(--border-subtle);
		min-height: 3.5rem;
		gap: 0.5rem;
		/* top accent line */
		box-shadow: inset 0 2px 0 rgba(96, 165, 250, 0.5);
	}
	.sidebar--collapsed .logo-row {
		justify-content: center;
		flex-direction: column;
		gap: 0.5rem;
	}

	.logo-text {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		padding-left: 0.25rem;
	}
	.logo-name {
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.25em;
		background: linear-gradient(90deg, #60a5fa 0%, #a78bfa 60%, #818cf8 100%);
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		filter: drop-shadow(0 0 8px rgba(96,165,250,0.5));
	}
	.logo-version {
		font-size: 0.58rem;
		color: var(--text-tertiary);
		letter-spacing: 0.05em;
	}
	.logo-collapsed {
		font-size: 0.78rem;
		font-weight: 700;
		letter-spacing: 0.15em;
		background: linear-gradient(135deg, #60a5fa, #a78bfa);
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		filter: drop-shadow(0 0 6px rgba(96,165,250,0.6));
	}

	.collapse-btn {
		color: var(--text-tertiary);
		padding: 0.25rem;
		border-radius: 0.2rem;
		border: none;
		background: transparent;
		cursor: pointer;
		transition: color 0.15s;
		display: flex;
		align-items: center;
	}
	.collapse-btn:hover { color: var(--accent); }

	.nav-link {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.52rem 0.625rem;
		border-radius: 0.25rem;
		border-left: 2px solid transparent;
		color: var(--text-secondary);
		text-decoration: none;
		transition: all 0.12s;
		font-size: 0.72rem;
		font-weight: 500;
		letter-spacing: 0.04em;
	}
	.nav-link:hover {
		background: rgba(96, 165, 250, 0.08);
		color: var(--text-primary);
		border-left-color: rgba(96, 165, 250, 0.3);
	}
	.nav-link--active {
		background: rgba(96, 165, 250, 0.14);
		border-left-color: var(--accent);
		color: var(--accent);
		box-shadow: inset 1px 0 12px rgba(96,165,250,0.06);
		text-shadow: 0 0 10px rgba(96,165,250,0.4);
	}
	.nav-link--active:hover { background: rgba(96, 165, 250, 0.18); }
	.nav-link--icon-only { justify-content: center; padding: 0.5rem; border-left: none; }

	/* Per-nav-item accent colors */
	.nav-link[data-nav="dashboard"]:hover, .nav-link[data-nav="dashboard"].nav-link--active { border-left-color: #818cf8; color: #818cf8; background: rgba(129,140,248,0.1); text-shadow: 0 0 10px rgba(129,140,248,0.4); }
	.nav-link[data-nav="tasks"]:hover, .nav-link[data-nav="tasks"].nav-link--active { border-left-color: #2dd4bf; color: #2dd4bf; background: rgba(45,212,191,0.1); text-shadow: 0 0 10px rgba(45,212,191,0.4); }
	.nav-link[data-nav="workflows"]:hover, .nav-link[data-nav="workflows"].nav-link--active { border-left-color: #a78bfa; color: #a78bfa; background: rgba(167,139,250,0.1); text-shadow: 0 0 10px rgba(167,139,250,0.4); }
	.nav-link[data-nav="agents"]:hover, .nav-link[data-nav="agents"].nav-link--active { border-left-color: #34d399; color: #34d399; background: rgba(52,211,153,0.1); text-shadow: 0 0 10px rgba(52,211,153,0.4); }
	.nav-link[data-nav="config"]:hover, .nav-link[data-nav="config"].nav-link--active { border-left-color: #94a3b8; color: #94a3b8; background: rgba(148,163,184,0.08); text-shadow: none; }
	.nav-link[data-nav="composer"]:hover, .nav-link[data-nav="composer"].nav-link--active { border-left-color: #fb923c; color: #fb923c; background: rgba(251,146,60,0.1); text-shadow: 0 0 10px rgba(251,146,60,0.4); }
	.nav-link[data-nav="studio"]:hover, .nav-link[data-nav="studio"].nav-link--active { border-left-color: #fb923c; color: #fb923c; background: rgba(251,146,60,0.1); text-shadow: 0 0 10px rgba(251,146,60,0.4); }
	.nav-link[data-nav="messages"]:hover, .nav-link[data-nav="messages"].nav-link--active { border-left-color: #fb7185; color: #fb7185; background: rgba(251,113,133,0.1); text-shadow: 0 0 10px rgba(251,113,133,0.4); }
	.nav-link[data-nav="intelligence"]:hover, .nav-link[data-nav="intelligence"].nav-link--active { border-left-color: #60a5fa; color: #60a5fa; background: rgba(96,165,250,0.12); text-shadow: 0 0 10px rgba(96,165,250,0.4); }

	.nav-icon { display: flex; align-items: center; flex-shrink: 0; }
	.nav-label { white-space: nowrap; }

	.ws-status {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 0.875rem;
		border-top: 1px solid var(--border-subtle);
	}
	.ws-status--collapsed { justify-content: center; }

	.offline-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: #f87171;
		box-shadow: 0 0 6px rgba(248,113,113,0.5);
		flex-shrink: 0;
	}

	.ws-label {
		font-size: 0.58rem;
		font-weight: 700;
		letter-spacing: 0.2em;
	}
	.ws-label--live {
		color: var(--running);
		text-shadow: 0 0 10px rgba(34, 211, 160, 0.7);
	}
	.ws-label--offline { color: #f87171; }

	.main-content {
		background: var(--bg-base);
		/* subtle indigo dot-grid pattern */
		background-image: radial-gradient(rgba(96,165,250,0.07) 1px, transparent 1px);
		background-size: 32px 32px;
	}

	.main-inner {
		padding: 1.75rem 2rem;
		max-width: 1400px;
	}
</style>
