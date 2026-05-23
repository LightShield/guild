<script>
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { connectWebSocket, wsConnected } from '$lib/stores.js';
	import '../app.css';

	const nav = [
		{ href: '/', label: 'Dashboard', icon: '&#9632;' },
		{ href: '/tasks', label: 'Tasks', icon: '&#9654;' },
		{ href: '/workflows', label: 'Workflows', icon: '&#8759;' },
		{ href: '/agents', label: 'Agents', icon: '&#9679;' },
		{ href: '/config', label: 'Config', icon: '&#9881;' },
		{ href: '/composer', label: 'Composer', icon: '&#9830;' },
		{ href: '/messages', label: 'Messages', icon: '&#9993;' }
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

<div class="flex h-screen bg-gray-950">
	<!-- Sidebar -->
	<aside class="{collapsed ? 'w-14' : 'w-60'} bg-gray-900 border-r border-gray-800 flex flex-col transition-all duration-200 shrink-0">
		<!-- Logo + collapse toggle -->
		<div class="px-3 py-4 border-b border-gray-800 flex items-center {collapsed ? 'justify-center' : 'justify-between'}">
			{#if !collapsed}
				<div class="px-2">
					<h1 class="text-lg font-bold text-guild-400 tracking-tight">Guild</h1>
					<p class="text-[10px] text-gray-600 uppercase tracking-wider font-medium">v0.2.0</p>
				</div>
			{/if}
			<button
				onclick={toggleSidebar}
				class="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors"
				title="{collapsed ? 'Expand' : 'Collapse'} sidebar"
			>
				{#if collapsed}
					<span class="text-sm">&#9655;</span>
				{:else}
					<span class="text-sm">&#9665;</span>
				{/if}
			</button>
		</div>

		<!-- Navigation -->
		<nav class="flex-1 px-2 py-3 space-y-0.5">
			{#each nav as item}
				{@const isActive = page.url.pathname === item.href || (item.href !== '/' && page.url.pathname.startsWith(item.href))}
				<a
					href={item.href}
					class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-150
						   {collapsed ? 'justify-center' : ''}
						   {isActive ? 'bg-gray-800 text-guild-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}"
					title={collapsed ? item.label : ''}
				>
					<span class="text-xs {isActive ? 'opacity-100' : 'opacity-60'}">{@html item.icon}</span>
					{#if !collapsed}
						<span class="font-medium">{item.label}</span>
					{/if}
				</a>
			{/each}
		</nav>

		<!-- Footer -->
		{#if !collapsed}
			<div class="px-5 py-4 border-t border-gray-800">
				<div class="flex items-center gap-2">
					<span class="w-1.5 h-1.5 rounded-full {$wsConnected ? 'bg-green-400' : 'bg-red-400'}"></span>
					<p class="text-[11px] text-gray-500 font-medium">
						{$wsConnected ? 'Connected' : 'Disconnected'}
					</p>
				</div>
			</div>
		{:else}
			<div class="py-4 flex justify-center">
				<span class="w-1.5 h-1.5 rounded-full {$wsConnected ? 'bg-green-400' : 'bg-red-400'}"></span>
			</div>
		{/if}
	</aside>

	<!-- Main content -->
	<main class="flex-1 overflow-y-auto p-8 bg-gray-950">
		<slot />
	</main>
</div>
