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

/**
 * Save a team configuration to the backend.
 * @param {string} name - Team name
 * @param {Array} nodes - Flow nodes (blocks with positions)
 * @param {Array} edges - Flow edges (connections)
 * @returns {Promise<any>}
 */
export async function saveTeam(name, nodes, edges) {
	// Convert flow nodes/edges into the team config format the backend expects
	const blocks = {};
	for (const node of nodes) {
		const blockName = node.data?.blockName || node.id;
		const role = node.data?.role || 'agent';
		blocks[node.id] = { name: blockName, role };
	}

	const connections = edges.map((edge) => ({
		source_block: edge.source,
		target_block: edge.target,
		source_port: 'output',
		target_port: 'input',
	}));

	return request('/teams', {
		method: 'POST',
		body: JSON.stringify({ name, blocks, connections }),
	});
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
