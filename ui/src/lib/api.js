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
 * Maps UI nodes/edges to the backend's TeamDef format (TOML-compatible).
 *
 * @param {string} name - Team name
 * @param {Array} nodes - Flow nodes (blocks with positions)
 * @param {Array} edges - Flow edges (port-to-port connections)
 * @returns {Promise<any>}
 */
export async function saveTeam(name, nodes, edges) {
	// Convert flow nodes to blocks with their type and position
	const blocks = {};
	for (const node of nodes) {
		if (node.type === 'group-boundary') continue; // skip visual-only nodes
		const blockName = node.data?.blockName || node.id;
		blocks[node.id] = {
			type: blockName,
			name: blockName,
			position: node.position,
		};
	}

	// Convert edges to port-to-port connections matching backend Connection format
	const connections = edges.map((edge) => {
		// Handle IDs are formatted as: nodeId__port__portId
		const sourcePort = edge.sourceHandle?.split('__port__')[1] || 'out';
		const targetPort = edge.targetHandle?.split('__port__')[1] || 'in';
		return {
			source_block: edge.source,
			source_port: sourcePort,
			target_block: edge.target,
			target_port: targetPort,
		};
	});

	// Determine entry block (first node with no incoming edges)
	const targets = new Set(connections.map(c => c.target_block));
	const entryBlock = Object.keys(blocks).find(id => !targets.has(id)) || Object.keys(blocks)[0] || '';

	return request('/teams', {
		method: 'POST',
		body: JSON.stringify({ name, blocks, connections, entry_block: entryBlock }),
	});
}

/**
 * Create a new block definition on the backend.
 * Writes a TOML file to .guild/blocks/{name}.toml
 */
export async function createBlock(block) {
	return request('/blocks', {
		method: 'POST',
		body: JSON.stringify(block),
	});
}

/**
 * Delete a block definition.
 */
export async function deleteBlock(name) {
	return request(`/blocks/${name}`, { method: 'DELETE' });
}

/**
 * Get full team definition by name.
 */
export async function fetchTeam(name) {
	return request(`/teams/${name}`);
}

/**
 * Delete a team.
 */
export async function deleteTeam(name) {
	return request(`/teams/${name}`, { method: 'DELETE' });
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
