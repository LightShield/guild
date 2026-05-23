<script>
  import { onMount } from 'svelte';
  import { fetchTaskEvents, fetchTaskMessages, fetchTasks } from '$lib/api.js';
  import { taskEvents, tasks } from '$lib/stores.js';

  let selectedTaskId = $state('');
  let loading = $state(true);
  let loadingMessages = $state(false);
  let taskDetail = $state(null);
  let messages = $state([]);
  let events = $state([]);
  let error = $state('');

  const orderedTasks = $derived(
    [...$tasks].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  );
  const selectedTask = $derived(orderedTasks.find((task) => task.task_id === selectedTaskId) || null);

  onMount(async () => {
    try {
      $tasks = await fetchTasks();
      selectedTaskId = orderedTasks[0]?.task_id || '';
      if (selectedTaskId) await loadMessages(selectedTaskId);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  });

  async function loadMessages(taskId) {
    selectedTaskId = taskId;
    loadingMessages = true;
    error = '';
    try {
      const data = await fetchTaskMessages(taskId);
      events = await fetchTaskEvents(taskId);
      taskDetail = data.task;
      messages = data.messages || [];
    } catch (e) {
      error = e.message;
      taskDetail = null;
      messages = [];
      events = [];
    } finally {
      loadingMessages = false;
    }
  }

  function roleClass(role) {
    if (role === 'assistant') return 'border-sky-800/70 bg-sky-950/20 text-sky-200';
    if (role === 'tool') return 'border-amber-800/70 bg-amber-950/20 text-amber-200';
    if (role === 'system') return 'border-purple-800/70 bg-purple-950/20 text-purple-200';
    return 'border-gray-800 bg-gray-900 text-gray-200';
  }
</script>

<svelte:head>
  <title>Guild - Messages</title>
</svelte:head>

<div class="h-[calc(100vh-4rem)] grid grid-cols-[340px_1fr] gap-0 -m-8">
  <aside class="border-r border-gray-800 bg-gray-950 overflow-hidden flex flex-col">
    <div class="px-5 py-4 border-b border-gray-800">
      <h2 class="text-base font-semibold text-gray-100">Task Messages</h2>
      <p class="text-xs text-gray-500 mt-1">Stored transcript per task agent</p>
    </div>

    <div class="flex-1 overflow-y-auto">
      {#if loading}
        <p class="p-5 text-sm text-gray-500">Loading tasks...</p>
      {:else if orderedTasks.length === 0}
        <p class="p-5 text-sm text-gray-500">No tasks yet.</p>
      {:else}
        {#each orderedTasks as task}
          <button
            onclick={() => loadMessages(task.task_id)}
            class="w-full text-left px-5 py-3 border-b border-gray-900 hover:bg-gray-900/80
                   {selectedTaskId === task.task_id ? 'bg-gray-900 border-l-2 border-l-guild-400' : ''}"
          >
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full
                {task.status === 'running' ? 'bg-green-300' :
                 task.status === 'completed' ? 'bg-sky-300' :
                 task.status === 'failed' || task.status === 'killed' ? 'bg-red-300' :
                 'bg-gray-400'}"></span>
              <span class="text-xs uppercase tracking-wider text-gray-500">{task.status}</span>
              <span class="ml-auto text-[11px] font-mono text-gray-600">{task.task_id?.slice(0, 8)}</span>
            </div>
            <p class="mt-1 text-sm text-gray-200 line-clamp-2">{task.description}</p>
            <p class="mt-1 text-[11px] text-gray-500 truncate">{task.assigned_agent || 'unassigned'}</p>
          </button>
        {/each}
      {/if}
    </div>
  </aside>

  <main class="bg-gray-950 overflow-hidden flex flex-col">
    {#if error}
      <div class="m-5 rounded border border-red-900/70 bg-red-950/30 px-4 py-3 text-sm text-red-200">
        {error}
      </div>
    {/if}

    {#if selectedTask}
      <div class="px-6 py-4 border-b border-gray-800 bg-gray-950">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h1 class="text-lg font-semibold text-gray-100 truncate">{selectedTask.description}</h1>
              <span class="px-2 py-0.5 rounded bg-gray-800 text-[11px] uppercase tracking-wider text-gray-400">
                {selectedTask.status}
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-500 font-mono break-all">{selectedTask.task_id}</p>
          </div>
          <div class="text-right shrink-0">
            <p class="text-xs text-gray-500">Agent</p>
            <p class="text-sm text-gray-300">{taskDetail?.assigned_agent || selectedTask.assigned_agent || '-'}</p>
          </div>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto p-6">
        {#if loadingMessages}
          <p class="text-sm text-gray-500">Loading messages...</p>
        {:else}
          <div class="grid gap-6 xl:grid-cols-[360px_1fr]">
            <section class="rounded border border-gray-800 bg-gray-900/50 p-4 h-fit">
              <h2 class="text-sm font-semibold text-gray-100">Timeline</h2>
              <div class="mt-4 space-y-3">
                {#each (events.length ? events : $taskEvents.filter((event) => event.task_id === selectedTask.task_id)) as event}
                  <div class="border-l border-gray-700 pl-3">
                    <div class="flex items-center gap-2">
                      <span class="text-[10px] uppercase tracking-wider text-guild-400">{event.event_type}</span>
                      <span class="text-[11px] text-gray-600">{event.timestamp}</span>
                    </div>
                    <p class="mt-1 text-xs text-gray-300">{event.message}</p>
                  </div>
                {:else}
                  <p class="text-xs text-gray-500">No timeline events for this task yet.</p>
                {/each}
              </div>
            </section>

            <section>
              {#if messages.length === 0}
                <div class="rounded border border-gray-800 bg-gray-900/60 p-5">
                  <p class="text-sm text-gray-300">No stored transcript for this task.</p>
                  <pre class="mt-3 whitespace-pre-wrap break-words rounded bg-gray-950 border border-gray-800 p-3 text-xs text-gray-400">{selectedTask.result || 'No result yet.'}</pre>
                </div>
              {:else}
                <div class="space-y-4">
                  {#each messages as message}
                    <article class="rounded border p-4 {roleClass(message.role)}">
                      <div class="flex items-center gap-2 mb-2">
                        <span class="text-xs font-semibold uppercase tracking-wider">{message.role}</span>
                        <span class="text-[11px] opacity-60">{message.created_at || message.timestamp || ''}</span>
                      </div>
                      <pre class="whitespace-pre-wrap break-words text-sm leading-relaxed font-sans">{message.content}</pre>
                    </article>
                  {/each}
                </div>
              {/if}
            </section>
          </div>
        {/if}
      </div>
    {:else}
      <div class="flex-1 flex items-center justify-center">
        <p class="text-sm text-gray-500">Select a task to inspect its messages.</p>
      </div>
    {/if}
  </main>
</div>
