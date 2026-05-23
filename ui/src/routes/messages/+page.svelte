<script>
  import { onMount } from 'svelte';
  import { fetchTaskEvents, fetchTaskMessages, fetchTasks, fetchTeams } from '$lib/api.js';
  import { taskEvents, tasks } from '$lib/stores.js';

  let selectedTaskId = $state('');
  let loading = $state(true);
  let expandedMsgIds = $state(new Set());
  function toggleMsgDesc(id, e) { e.stopPropagation(); const s = new Set(expandedMsgIds); s.has(id) ? s.delete(id) : s.add(id); expandedMsgIds = s; }
  let loadingMessages = $state(false);
  let taskDetail = $state(null);
  let messages = $state([]);
  let events = $state([]);
  let error = $state('');
  let search = $state('');
  let statusFilter = $state('all');
  let typeFilter = $state('all');
  let teams = $state([]);
  let copiedMap = $state({});
  function copyText(key, text) {
    navigator.clipboard.writeText(text ?? '');
    copiedMap = { ...copiedMap, [key]: true };
    setTimeout(() => { copiedMap = { ...copiedMap, [key]: false }; }, 1500);
  }

  const orderedTasks = $derived.by(() => {
    const term = search.trim().toLowerCase();
    return [...$tasks]
      .filter((task) => statusFilter === 'all' || task.status === statusFilter)
      .filter((task) => typeFilter === 'all' || taskKind(task) === typeFilter)
      .filter((task) => {
        if (!term) return true;
        return [task.task_id, task.description, task.assigned_agent, workflowName(task)]
          .some((value) => String(value || '').toLowerCase().includes(term));
      })
      .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  });
  const selectedTask = $derived(orderedTasks.find((task) => task.task_id === selectedTaskId) || null);

  onMount(async () => {
    try {
      const [loadedTasks, loadedTeams] = await Promise.all([
        fetchTasks(),
        fetchTeams().catch(() => []),
      ]);
      $tasks = loadedTasks;
      teams = loadedTeams;
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

  function parentWorkflow(task) {
    const agent = task.assigned_agent || '';
    const event = $taskEvents.find((item) => item.event_type === 'agent_spawned' && item.agent_id === agent);
    if (!event) return null;
    return $tasks.find((candidate) => candidate.task_id === event.task_id) || null;
  }

  function workflowName(task) {
    const agent = task.assigned_agent || '';
    return task.workflow_name || task.execution_id || parentWorkflow(task)?.assigned_agent || (teams.some((team) => team.name === agent) ? agent : '');
  }

  function taskKind(task) {
    const agent = task.assigned_agent || '';
    if (task.description?.startsWith('[') || /^[A-Za-z0-9_-]+-[0-9a-f]{8}$/.test(agent)) return 'workflow_block';
    if (teams.some((team) => team.name === agent)) return 'workflow';
    if (String(task.result || '').includes('Completed blocks:') || task.execution_id) return 'workflow';
    return agent && agent !== '-' ? 'agent' : 'task';
  }

  function typeLabel(type) {
    return {
      workflow: 'Workflow',
      workflow_block: 'Block',
      agent: 'Agent',
      task: 'Task',
    }[type] || type;
  }
</script>

<svelte:head>
  <title>Guild — Messages</title>
</svelte:head>

<div class="msg-layout">
  <!-- Task list sidebar -->
  <aside class="msg-sidebar">
    <div class="msg-sidebar-head">
      <div>
        <div class="label-xs prompt-label" style="margin-bottom: 0.3rem">transcripts</div>
        <div class="sidebar-title">Messages</div>
      </div>
      <input type="search" bind:value={search} placeholder="Search..." class="input-field" style="font-size: 0.72rem; padding: 0.375rem 0.625rem" />
      <div class="sidebar-filters">
        <select bind:value={statusFilter} class="select-field" style="flex: 1">
          <option value="all">All status</option>
          <option value="pending">Pending</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="killed">Killed</option>
        </select>
        <select bind:value={typeFilter} class="select-field" style="flex: 1">
          <option value="all">All types</option>
          <option value="workflow">Workflow</option>
          <option value="workflow_block">Block</option>
          <option value="agent">Agent</option>
          <option value="task">Task</option>
        </select>
      </div>
    </div>

    <div class="msg-task-list">
      {#if loading}
        <div class="list-state">Loading...</div>
      {:else if orderedTasks.length === 0}
        <div class="list-state">No tasks yet.</div>
      {:else}
        {#each orderedTasks as task}
          <button onclick={() => loadMessages(task.task_id)} class="task-item task-item--{task.status} {selectedTaskId === task.task_id ? 'task-item--active' : ''}">
            <div class="task-item-top">
              {#if task.status === 'running'}
                <span class="running-dot"></span>
              {:else}
                <span class="status-dot-sm status-dot-sm--{task.status}"></span>
              {/if}
              <span class="task-item-status">{task.status}</span>
              <span class="task-item-id">{task.task_id?.slice(0, 8)}</span>
            </div>
            <p class="task-item-desc expandable-text {expandedMsgIds.has(task.task_id) ? 'expandable-text--open' : ''}" onclick={(e) => toggleMsgDesc(task.task_id, e)}>{task.description}</p>
            <div class="task-item-meta">
              <span>{typeLabel(taskKind(task))}</span>
              <span class="meta-sep">/</span>
              <span class="task-item-agent">{task.assigned_agent || 'unassigned'}</span>
            </div>
            {#if workflowName(task)}
              <p class="task-item-origin">← {workflowName(task)}</p>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </aside>

  <!-- Main panel -->
  <main class="msg-main">
    {#if error}
      <div class="error-bar">{error}</div>
    {/if}

    {#if selectedTask}
      <div class="msg-task-header">
        <div class="msg-task-header-left">
          <div class="task-title-row">
            <h1 class="task-title">{selectedTask.description}</h1>
            <span class="status-badge status-{selectedTask.status}">{selectedTask.status}</span>
          </div>
          <p class="task-id-mono">{selectedTask.task_id}</p>
        </div>
        <div class="msg-task-header-right">
          <div class="meta-item">
            <span class="meta-key">agent</span>
            <span class="meta-val">{taskDetail?.assigned_agent || selectedTask.assigned_agent || '—'}</span>
          </div>
          {#if workflowName(selectedTask)}
            <div class="meta-item">
              <span class="meta-key">origin</span>
              <span class="meta-val" style="color: var(--accent)">{workflowName(selectedTask)}</span>
            </div>
          {/if}
        </div>
      </div>

      <div class="msg-body">
        {#if loadingMessages}
          <div class="loading-state"><span class="running-dot"></span><span>Loading messages...</span></div>
        {:else}
          <div class="msg-content-grid">
            <!-- Timeline -->
            <section class="timeline-panel">
              <div class="label-xs prompt-label" style="margin-bottom: 0.75rem">timeline</div>
              <div class="timeline-events">
                {#each (events.length ? events : $taskEvents.filter((ev) => ev.task_id === selectedTask.task_id)) as event}
                  <div class="t-event">
                    <div class="t-event-head">
                      <span class="t-event-type">{event.event_type}</span>
                      <span class="t-event-time">{event.timestamp}</span>
                    </div>
                    <p class="t-event-msg">{event.message}</p>
                  </div>
                {:else}
                  <p class="no-data">No events yet.</p>
                {/each}
              </div>
            </section>

            <!-- Messages -->
            <section class="messages-panel">
              {#if messages.length === 0}
                <div class="no-transcript">
                  <div class="label-xs prompt-label" style="margin-bottom: 0.5rem">result</div>
                  <div class="copyable-block">
                    <button class="copy-btn" onclick={() => copyText('result', selectedTask.result || '')}>
                      {copiedMap['result'] ? '✓ Copied' : 'Copy'}
                    </button>
                    <pre class="result-pre">{selectedTask.result || 'No result yet.'}</pre>
                  </div>
                </div>
              {:else}
                <div class="label-xs prompt-label" style="margin-bottom: 0.75rem">transcript · {messages.length} messages</div>
                <div class="message-list">
                  {#each messages as message}
                    <article class="msg-bubble msg-bubble--{message.role}">
                      <div class="msg-bubble-head">
                        <span class="msg-role">{message.role}</span>
                        <span class="msg-time">{message.created_at || message.timestamp || ''}</span>
                      </div>
                      <div class="copyable-block">
                        <button class="copy-btn" onclick={() => copyText(message.id || message.created_at || String(message.role), message.content)}>
                          {copiedMap[message.id || message.created_at || String(message.role)] ? '✓ Copied' : 'Copy'}
                        </button>
                        <pre class="msg-content">{message.content}</pre>
                      </div>
                    </article>
                  {/each}
                </div>
              {/if}
            </section>
          </div>
        {/if}
      </div>
    {:else}
      <div class="msg-empty">
        <p>Select a task to inspect its transcript.</p>
      </div>
    {/if}
  </main>
</div>

<style>
  .msg-layout {
    display: grid;
    grid-template-columns: 300px 1fr;
    height: calc(100vh - 3.5rem);
    margin: -1.75rem -2rem;
    overflow: hidden;
  }

  .msg-sidebar {
    background: var(--bg-surface);
    border-right: 1px solid var(--border-default);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .msg-sidebar-head {
    padding: 1rem 1rem 0.75rem;
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .sidebar-title {
    font-size: 0.85rem;
    font-weight: 700;
    background: linear-gradient(90deg, var(--text-primary) 55%, var(--text-secondary));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .sidebar-filters { display: flex; gap: 0.375rem; }

  .msg-task-list { flex: 1; overflow-y: auto; }
  .list-state { padding: 1.25rem; font-size: 0.78rem; color: var(--text-secondary); }

  .task-item {
    width: 100%;
    text-align: left;
    padding: 0.625rem 1rem;
    border-bottom: 1px solid var(--border-subtle);
    border-left: 2px solid transparent;
    background: transparent;
    cursor: pointer;
    transition: background 0.1s;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .task-item:hover { background: var(--bg-hover); }
  .task-item--active {
    background: rgba(56, 189, 248, 0.06);
    border-left-color: var(--accent);
  }
  .task-item--running { border-left-color: rgba(74, 222, 128, 0.7); background: rgba(74, 222, 128, 0.025); }
  .task-item--failed  { border-left-color: rgba(248, 113, 113, 0.5); }
  .task-item--killed  { border-left-color: rgba(251, 191, 36, 0.4); }
  .task-item--completed { border-left-color: rgba(56, 189, 248, 0.3); }

  .task-item-top { display: flex; align-items: center; gap: 0.375rem; }
  .task-item-status { font-size: 0.68rem; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-secondary); }
  .task-item-id { margin-left: auto; font-size: 0.68rem; font-family: inherit; color: var(--text-tertiary); }
  .task-item-desc { font-size: 0.78rem; color: var(--text-primary); }
  .task-item-meta { display: flex; align-items: center; gap: 0.25rem; font-size: 0.7rem; color: var(--text-secondary); }
  .meta-sep { color: var(--text-tertiary); }
  .task-item-agent { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .task-item-origin { font-size: 0.68rem; color: var(--accent); opacity: 0.8; }

  .status-dot-sm {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
  }
  .status-dot-sm--running { background: var(--running); }
  .status-dot-sm--completed { background: #38bdf8; }
  .status-dot-sm--failed, .status-dot-sm--killed { background: #f87171; }
  .status-dot-sm--pending { background: var(--text-tertiary); }

  .msg-main {
    background: var(--bg-base);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .error-bar {
    margin: 0.75rem;
    padding: 0.625rem 0.875rem;
    background: rgba(248, 113, 113, 0.08);
    border: 1px solid rgba(248, 113, 113, 0.2);
    border-radius: 0.15rem;
    font-size: 0.78rem;
    color: #f87171;
  }

  .msg-task-header {
    padding: 0.875rem 1.25rem;
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    background: var(--bg-surface);
    flex-shrink: 0;
  }
  .msg-task-header-left { min-width: 0; flex: 1; }
  .task-title-row { display: flex; align-items: center; gap: 0.625rem; }
  .task-title {
    font-size: 0.9rem;
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    background: linear-gradient(90deg, var(--text-primary) 70%, var(--text-secondary));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .task-id-mono { font-size: 0.68rem; color: var(--text-tertiary); margin-top: 0.25rem; word-break: break-all; }
  .msg-task-header-right { flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; }
  .meta-item { display: flex; align-items: center; gap: 0.375rem; }
  .meta-key { font-size: 0.68rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.08em; }
  .meta-val { font-size: 0.75rem; color: var(--text-primary); }

  .msg-body { flex: 1; overflow-y: auto; padding: 1.25rem; }
  .loading-state { display: flex; align-items: center; gap: 0.625rem; font-size: 0.78rem; color: var(--text-secondary); }

  .msg-content-grid {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 1.25rem;
    align-items: start;
  }

  .timeline-panel {
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 0.15rem;
    padding: 1rem;
    position: sticky;
    top: 0;
  }
  .timeline-events { display: flex; flex-direction: column; gap: 0.5rem; }
  .t-event { border-left: 2px solid var(--border-default); padding-left: 0.625rem; }
  .t-event-head { display: flex; align-items: center; gap: 0.5rem; }
  .t-event-type { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }
  .t-event-time { font-size: 0.68rem; color: var(--text-tertiary); }
  .t-event-msg { font-size: 0.7rem; color: var(--text-primary); margin-top: 0.2rem; line-height: 1.4; }
  .no-data { font-size: 0.72rem; color: var(--text-secondary); }

  .messages-panel { }
  .message-list { display: flex; flex-direction: column; gap: 0.625rem; }

  .msg-bubble {
    border-left: 3px solid;
    border-radius: 0.15rem;
    padding: 0.75rem 0.875rem;
    border-top: 1px solid;
    border-right: 1px solid;
    border-bottom: 1px solid;
  }
  .msg-bubble--assistant {
    border-left-color: #38bdf8;
    background: rgba(56, 189, 248, 0.04);
    border-color: rgba(56, 189, 248, 0.12);
    border-left-color: #38bdf8;
  }
  .msg-bubble--user {
    border-left-color: var(--text-secondary);
    background: rgba(255,255,255,0.02);
    border-color: var(--border-subtle);
  }
  .msg-bubble--tool {
    border-left-color: #fbbf24;
    background: rgba(251, 191, 36, 0.04);
    border-color: rgba(251, 191, 36, 0.12);
  }
  .msg-bubble--system {
    border-left-color: #a78bfa;
    background: rgba(167, 139, 250, 0.04);
    border-color: rgba(167, 139, 250, 0.12);
  }

  .msg-bubble-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
  .msg-role {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .msg-bubble--assistant .msg-role { color: #38bdf8; }
  .msg-bubble--tool .msg-role { color: #fbbf24; }
  .msg-bubble--system .msg-role { color: #a78bfa; }
  .msg-bubble--user .msg-role { color: var(--text-secondary); }
  .msg-time { font-size: 0.68rem; color: var(--text-tertiary); }

  .msg-content {
    white-space: pre-wrap;
    word-break: break-words;
    font-size: 0.78rem;
    line-height: 1.6;
    color: var(--text-primary);
    font-family: inherit;
  }

  .no-transcript { }
  .result-pre {
    white-space: pre-wrap;
    word-break: break-words;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 0.15rem;
    padding: 0.75rem;
    font-size: 0.75rem;
    color: var(--text-primary);
    font-family: inherit;
    line-height: 1.5;
  }

  .msg-empty {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    color: var(--text-secondary);
  }
</style>
