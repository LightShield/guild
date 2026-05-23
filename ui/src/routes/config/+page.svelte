<script>
	import { onMount } from 'svelte';
	import { fetchConfig, updateConfig } from '$lib/api.js';
	import { config } from '$lib/stores.js';

	let loading = $state(true);
	let saving = $state(false);
	let editedConfig = $state('');
	let message = $state('');
	let mode = $state('form');
	let draft = $state({});

	const providers = ['codex', 'claude', 'ollama', 'openai'];
	const permissionOptions = ['ask', 'autopilot', 'scoped'];
	const sandboxOptions = ['auto', 'docker', 'none'];

	onMount(async () => {
		try {
			const loaded = await fetchConfig();
			$config = loaded;
			draft = { ...loaded };
			editedConfig = JSON.stringify(loaded, null, 2);
		} catch (e) {
			console.error('Failed to load config:', e);
		} finally {
			loading = false;
		}
	});

	function numberValue(value, fallback = 0) {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : fallback;
	}

	function boolValue(value) {
		return value === true || value === 'true';
	}

	function updateDraft(key, value) {
		draft = { ...draft, [key]: value };
		editedConfig = JSON.stringify(draft, null, 2);
	}

	async function handleSave() {
		saving = true;
		message = '';
		try {
			const payload = mode === 'json' ? JSON.parse(editedConfig) : draft;
			await updateConfig(payload);
			$config = payload;
			draft = { ...payload };
			editedConfig = JSON.stringify(payload, null, 2);
			message = 'Configuration saved.';
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

<div class="space-y-6">
	<div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
		<div>
			<h2 class="text-2xl font-bold">Configuration</h2>
			<p class="mt-1 text-sm text-gray-500">Common runtime settings. JSON is available for advanced edits.</p>
		</div>
		<div class="inline-flex rounded border border-gray-800 bg-gray-900 p-1">
			<button type="button" onclick={() => (mode = 'form')} class="rounded px-3 py-1.5 text-xs font-semibold {mode === 'form' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}">Form</button>
			<button type="button" onclick={() => (mode = 'json')} class="rounded px-3 py-1.5 text-xs font-semibold {mode === 'json' ? 'bg-guild-600 text-white' : 'text-gray-400 hover:text-gray-200'}">JSON</button>
		</div>
	</div>

	{#if loading}
		<div class="text-gray-400">Loading configuration...</div>
	{:else}
		<div class="bg-gray-900 rounded-lg border border-gray-800">
			<div class="p-5 border-b border-gray-800 flex items-center justify-between">
				<div>
					<h3 class="text-lg font-semibold">Project Config</h3>
					<p class="text-xs text-gray-500">Saved to this project's Guild config.</p>
				</div>
				<button onclick={handleSave} disabled={saving} class="px-4 py-2 bg-guild-600 hover:bg-guild-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium text-sm">
					{saving ? 'Saving...' : 'Save'}
				</button>
			</div>

			{#if mode === 'form'}
				<div class="grid gap-6 p-5 xl:grid-cols-2">
					<section class="space-y-4">
						<h4 class="text-sm font-semibold uppercase text-gray-500">Provider</h4>
						<label class="block">
							<span class="text-xs text-gray-500">Provider</span>
							<select value={draft.provider_name || ''} onchange={(e) => updateDraft('provider_name', e.currentTarget.value)} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100">
								{#each providers as provider}
									<option value={provider}>{provider}</option>
								{/each}
							</select>
						</label>
						<label class="block">
							<span class="text-xs text-gray-500">Model</span>
							<input value={draft.model || ''} oninput={(e) => updateDraft('model', e.currentTarget.value)} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
						</label>
						<label class="block">
							<span class="text-xs text-gray-500">Base URL</span>
							<input value={draft.base_url || ''} oninput={(e) => updateDraft('base_url', e.currentTarget.value)} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
						</label>
						<div class="grid gap-3 sm:grid-cols-2">
							<label class="block">
								<span class="text-xs text-gray-500">Temperature</span>
								<input type="number" step="0.1" value={draft.temperature ?? 0.7} oninput={(e) => updateDraft('temperature', numberValue(e.currentTarget.value, 0.7))} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
							</label>
							<label class="block">
								<span class="text-xs text-gray-500">Max tokens</span>
								<input type="number" value={draft.max_tokens ?? 4096} oninput={(e) => updateDraft('max_tokens', numberValue(e.currentTarget.value, 4096))} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
							</label>
						</div>
					</section>

					<section class="space-y-4">
						<h4 class="text-sm font-semibold uppercase text-gray-500">Execution</h4>
						<div class="grid gap-3 sm:grid-cols-2">
							<label class="block">
								<span class="text-xs text-gray-500">Default permission</span>
								<select value={draft.default_permission || 'ask'} onchange={(e) => updateDraft('default_permission', e.currentTarget.value)} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100">
									{#each permissionOptions as permission}
										<option value={permission}>{permission}</option>
									{/each}
								</select>
							</label>
							<label class="block">
								<span class="text-xs text-gray-500">Max concurrent agents</span>
								<input type="number" min="1" value={draft.max_concurrent_agents ?? 1} oninput={(e) => updateDraft('max_concurrent_agents', numberValue(e.currentTarget.value, 1))} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
							</label>
						</div>
						<div class="grid gap-3 sm:grid-cols-2">
							<label class="block">
								<span class="text-xs text-gray-500">CLI provider timeout seconds</span>
								<input type="number" value={draft.cli_provider_timeout_seconds ?? 300} oninput={(e) => updateDraft('cli_provider_timeout_seconds', numberValue(e.currentTarget.value, 300))} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
							</label>
							<label class="block">
								<span class="text-xs text-gray-500">Default max turns</span>
								<input type="number" value={draft.default_max_turns ?? 25} oninput={(e) => updateDraft('default_max_turns', numberValue(e.currentTarget.value, 25))} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100" />
							</label>
						</div>
						<label class="block">
							<span class="text-xs text-gray-500">Escalation CLI providers</span>
							<input value={draft.escalation_cli_providers || ''} oninput={(e) => updateDraft('escalation_cli_providers', e.currentTarget.value)} placeholder="codex,claude" class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder-gray-600" />
						</label>
					</section>

					<section class="space-y-4">
						<h4 class="text-sm font-semibold uppercase text-gray-500">Security</h4>
						<div class="grid gap-3 sm:grid-cols-2">
							<label class="block">
								<span class="text-xs text-gray-500">Sandbox mode</span>
								<select value={draft.sandbox_mode || 'auto'} onchange={(e) => updateDraft('sandbox_mode', e.currentTarget.value)} class="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100">
									{#each sandboxOptions as option}
										<option value={option}>{option}</option>
									{/each}
								</select>
							</label>
							<label class="flex items-center gap-3 rounded border border-gray-800 bg-gray-950 px-3 py-2 mt-5">
								<input type="checkbox" checked={boolValue(draft.sandbox_network)} onchange={(e) => updateDraft('sandbox_network', e.currentTarget.checked)} />
								<span class="text-sm text-gray-300">Sandbox network</span>
							</label>
						</div>
					</section>

					<section class="space-y-4">
						<h4 class="text-sm font-semibold uppercase text-gray-500">Daemon</h4>
						<label class="flex items-center gap-3 rounded border border-gray-800 bg-gray-950 px-3 py-2">
							<input type="checkbox" checked={boolValue(draft.auto_recovery)} onchange={(e) => updateDraft('auto_recovery', e.currentTarget.checked)} />
							<span class="text-sm text-gray-300">Auto recovery</span>
						</label>
						<label class="flex items-center gap-3 rounded border border-gray-800 bg-gray-950 px-3 py-2">
							<input type="checkbox" checked={boolValue(draft.presence_aware_notifications)} onchange={(e) => updateDraft('presence_aware_notifications', e.currentTarget.checked)} />
							<span class="text-sm text-gray-300">Presence-aware notifications</span>
						</label>
					</section>
				</div>
			{:else}
				<div class="p-5">
					<textarea bind:value={editedConfig} rows="22" class="w-full px-4 py-3 bg-gray-950 border border-gray-700 rounded-lg text-gray-100 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-guild-500 resize-y"></textarea>
				</div>
			{/if}

			{#if message}
				<p class="px-5 pb-5 text-sm {message.startsWith('Error') ? 'text-red-400' : 'text-green-400'}">{message}</p>
			{/if}
		</div>
	{/if}
</div>
