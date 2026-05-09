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
