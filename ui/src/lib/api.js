const BASE_URL = '/api';

/**
 * Generic fetch wrapper with error handling.
 * @param {string} path
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
async function request(path, options = {}) {
	const res = await fetch(`${BASE_URL}${path}`, {
		headers: { 'Content-Type': 'application/json', ...options.headers },
		...options
	});
	if (!res.ok) {
		throw new Error(`API error: ${res.status} ${res.statusText}`);
	}
	return res.json();
}

export async function fetchStatus() {
	return request('/status');
}

export async function fetchTasks() {
	return request('/tasks');
}

export async function fetchTask(id) {
	return request(`/tasks/${id}`);
}

export async function fetchAgents() {
	return request('/agents');
}

export async function fetchConfig() {
	return request('/config');
}

export async function updateConfig(config) {
	return request('/config', {
		method: 'POST',
		body: JSON.stringify(config)
	});
}

export async function fetchAudit(limit = 50) {
	return request(`/audit?limit=${limit}`);
}

export async function fetchLearnings() {
	return request('/learnings');
}

export async function fetchBlocks() {
	return request('/blocks');
}

export async function fetchTeams() {
	return request('/teams');
}

export async function createTask(description) {
	return request('/tasks', {
		method: 'POST',
		body: JSON.stringify({ description })
	});
}

export async function killTask(id) {
	return request(`/tasks/${id}/kill`, { method: 'POST' });
}

export async function pauseTask(id) {
	return request(`/tasks/${id}/pause`, { method: 'POST' });
}

export async function resumeTask(id) {
	return request(`/tasks/${id}/resume`, { method: 'POST' });
}
