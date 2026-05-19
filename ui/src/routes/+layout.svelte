<script>
	import { onMount, onDestroy } from 'svelte';
	import { connectWebSocket, wsConnected } from '$lib/stores.js';
	import '../app.css';

	const nav = [
		{ href: '/', label: 'Dashboard', icon: '&#9632;' },
		{ href: '/tasks', label: 'Tasks', icon: '&#9654;' },
		{ href: '/agents', label: 'Agents', icon: '&#9679;' },
		{ href: '/config', label: 'Config', icon: '&#9881;' },
		{ href: '/composer', label: 'Composer', icon: '&#9830;' },
		{ href: '/messages', label: 'Messages', icon: '&#9993;' }
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

<div class="flex h-screen bg-gray-950">
	<!-- Sidebar -->
	<aside class="w-60 bg-gray-900 border-r border-gray-800 flex flex-col">
		<!-- Logo -->
		<div class="px-5 py-5 border-b border-gray-800">
			<h1 class="text-lg font-bold text-guild-400 tracking-tight">Guild</h1>
			<p class="text-[10px] text-gray-600 mt-0.5 uppercase tracking-wider font-medium">Agent Harness v0.2.0</p>
		</div>

		<!-- Navigation -->
		<nav class="flex-1 px-3 py-4 space-y-0.5">
			{#each nav as item}
				<a
					href={item.href}
					class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-400
						   hover:bg-gray-800 hover:text-gray-100 transition-all duration-150"
				>
					<span class="text-xs opacity-60">{@html item.icon}</span>
					<span class="font-medium">{item.label}</span>
				</a>
			{/each}
		</nav>

		<!-- Footer -->
		<div class="px-5 py-4 border-t border-gray-800">
			<div class="flex items-center gap-2">
				<span class="w-1.5 h-1.5 rounded-full {$wsConnected ? 'bg-green-400' : 'bg-red-400'}"></span>
				<p class="text-[11px] text-gray-500 font-medium">
					{$wsConnected ? 'Connected' : 'Disconnected'}
				</p>
			</div>
		</div>
	</aside>

	<!-- Main content -->
	<main class="flex-1 overflow-y-auto p-8 bg-gray-950">
		<slot />
	</main>
</div>
