<script>
	import { onMount, onDestroy } from 'svelte';
	import { connectWebSocket, wsConnected } from '$lib/stores.js';
	import '../app.css';

	const nav = [
		{ href: '/', label: 'Dashboard', icon: '&#9632;' },
		{ href: '/tasks', label: 'Tasks', icon: '&#9654;' },
		{ href: '/agents', label: 'Agents', icon: '&#9679;' },
		{ href: '/config', label: 'Config', icon: '&#9881;' },
		{ href: '/composer', label: 'Composer', icon: '&#9830;' }
	];

	let ws = null;

	onMount(() => {
		ws = connectWebSocket();
	});

	onDestroy(() => {
		if (ws) {
			ws.close();
		}
	});
</script>

<div class="flex h-screen">
	<!-- Sidebar -->
	<aside class="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
		<!-- Logo -->
		<div class="p-6 border-b border-gray-700">
			<h1 class="text-xl font-bold text-guild-400">Guild</h1>
			<p class="text-xs text-gray-500 mt-1">v0.2.0</p>
		</div>

		<!-- Navigation -->
		<nav class="flex-1 p-4 space-y-1">
			{#each nav as item}
				<a
					href={item.href}
					class="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-300
						   hover:bg-gray-700 hover:text-white transition-colors"
				>
					<span class="text-sm">{@html item.icon}</span>
					<span>{item.label}</span>
				</a>
			{/each}
		</nav>

		<!-- Footer -->
		<div class="p-4 border-t border-gray-700">
			<div class="flex items-center gap-2">
				<span class="w-2 h-2 rounded-full {$wsConnected ? 'bg-green-400' : 'bg-red-400'}"></span>
				<p class="text-xs text-gray-500">
					{$wsConnected ? 'Connected' : 'Disconnected'}
				</p>
			</div>
			<p class="text-xs text-gray-500 mt-1">Local Agent Harness</p>
		</div>
	</aside>

	<!-- Main content -->
	<main class="flex-1 overflow-y-auto p-8">
		<slot />
	</main>
</div>
