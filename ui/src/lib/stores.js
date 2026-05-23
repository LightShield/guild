import { writable } from 'svelte/store';

/** @type {import('svelte/store').Writable<Array>} */
export const tasks = writable([]);

/** @type {import('svelte/store').Writable<Array>} */
export const agents = writable([]);

/** @type {import('svelte/store').Writable<object|null>} */
export const status = writable(null);

/** @type {import('svelte/store').Writable<object|null>} */
export const config = writable(null);

/** @type {import('svelte/store').Writable<Array>} */
export const learnings = writable([]);

/** @type {import('svelte/store').Writable<Array>} */
export const audit = writable([]);

/** @type {import('svelte/store').Writable<Array>} */
export const taskEvents = writable([]);

/** @type {import('svelte/store').Writable<boolean>} */
export const wsConnected = writable(false);

/**
 * Connect a WebSocket to the Guild API for real-time status updates.
 * Automatically updates the status, tasks, and agents stores on messages.
 * @returns {WebSocket}
 */
export function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        wsConnected.set(true);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        status.set(data);
        if (data.tasks) tasks.set(data.tasks);
        if (data.agents) agents.set(data.agents);
        if (data.task_events) taskEvents.set(data.task_events);
    };

    ws.onclose = () => {
        wsConnected.set(false);
    };

    ws.onerror = () => {
        wsConnected.set(false);
    };

    return ws;
}
