<script>
	import { onMount } from 'svelte';
	import { fetchConfig, updateConfig } from '$lib/api.js';
	import { config } from '$lib/stores.js';

	let loading = true;
	let saving = false;
	let editedConfig = '';
	let message = '';

	onMount(async () => {
		try {
			$config = await fetchConfig();
			editedConfig = JSON.stringify($config, null, 2);
		} catch (e) {
			console.error('Failed to load config:', e);
		} finally {
			loading = false;
		}
	});

	async function handleSave() {
		saving = true;
		message = '';
		try {
			const parsed = JSON.parse(editedConfig);
			await updateConfig(parsed);
			$config = parsed;
			message = 'Configuration saved successfully.';
		} catch (e) {
			message = `Error: ${e.message}`;
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head>
	<title>Guild - Config</title>
</svelte:head>

<div class="space-y-8">
	<h2 class="text-2xl font-bold">Configuration</h2>

	{#if loading}
		<div class="text-gray-400">Loading configuration...</div>
	{:else}
		<div class="bg-gray-800 rounded-xl border border-gray-700">
			<div class="p-6 border-b border-gray-700 flex items-center justify-between">
				<h3 class="text-lg font-semibold">Project Config</h3>
				<button
					on:click={handleSave}
					disabled={saving}
					class="px-4 py-2 bg-guild-600 hover:bg-guild-500 disabled:bg-gray-600
						   disabled:cursor-not-allowed text-white rounded-lg transition-colors
						   font-medium text-sm"
				>
					{saving ? 'Saving...' : 'Save'}
				</button>
			</div>
			<div class="p-6">
				<textarea
					bind:value={editedConfig}
					rows="20"
					class="w-full px-4 py-3 bg-gray-900 border border-gray-600 rounded-lg
						   text-gray-100 font-mono text-sm focus:outline-none focus:ring-2
						   focus:ring-guild-500 focus:border-transparent resize-y"
				></textarea>
				{#if message}
					<p class="mt-3 text-sm {message.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">
						{message}
					</p>
				{/if}
			</div>
		</div>
	{/if}
</div>
