"""Learning loop — extract knowledge from completed tasks."""

from __future__ import annotations

import json
import logging

from guild.core.agent import AgentLoop
from guild.core.models import BlockDef, PermissionTier
from guild.core.storage import Storage
from guild.providers.base import LLMProvider

log = logging.getLogger(__name__)

LEARNER_PROMPT = """\
You are a learning extractor. Review the session logs of a completed task and extract useful knowledge.

For each learning, output a JSON line with:
- "category": one of "pattern", "anti_pattern", "tool_tip", "domain_knowledge"
- "content": a concise, actionable description
- "confidence": 0.0 to 1.0 (how confident you are this is a real, reusable insight)

Only extract genuinely useful insights. Skip trivial observations.
Output one JSON object per line, nothing else.
"""


async def extract_learnings(
    task_id: str,
    storage: Storage,
    provider: LLMProvider,
) -> list[dict]:
    """Run the learner on a completed task's logs and store results."""
    # Gather task info and messages from all agents that worked on it
    task = await storage.get_task(task_id)
    if not task:
        return []

    agents = await storage.list_agents()
    task_agents = [a for a in agents if a.get("task_id") == task_id]

    # Collect all messages from task agents
    all_messages = []
    for agent in task_agents:
        msgs = await storage.get_messages(agent["agent_id"])
        all_messages.extend(msgs)

    if not all_messages:
        # Fallback: get messages from the assigned agent
        if task.get("assigned_agent"):
            all_messages = await storage.get_messages(task["assigned_agent"])

    if not all_messages:
        log.info(f"No messages found for task {task_id}, skipping learning extraction")
        return []

    # Build a summary of what happened
    summary_parts = [
        f"Task: {task['description']}",
        f"Status: {task['status']}",
        f"Result: {task.get('result', 'N/A')}",
        "",
        "Session log (last 50 messages):",
    ]
    for msg in all_messages[-50:]:
        role = msg.get("role", "?")
        content = str(msg.get("content", ""))[:500]
        summary_parts.append(f"[{role}] {content}")

    summary = "\n".join(summary_parts)

    # Create a learner agent
    learner_block = BlockDef(
        name="learner",
        role="learner",
        system_prompt=LEARNER_PROMPT,
        tools=[],
        permission=PermissionTier.NOTHING,
    )

    agent = AgentLoop(
        agent_id=f"learner-{task_id[:8]}",
        block=learner_block,
        provider=provider,
        storage=storage,
    )
    await agent.initialize()
    result = await agent.run(summary, max_turns=1)

    # Parse learnings from result
    learnings = []
    for line in result.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            if "category" in data and "content" in data:
                learning = {
                    "category": data["category"],
                    "content": data["content"],
                    "confidence": float(data.get("confidence", 0.5)),
                    "source_task_id": task_id,
                }
                learnings.append(learning)
        except (json.JSONDecodeError, ValueError):
            continue

    # Store learnings
    for l in learnings:
        await storage.add_learning(
            category=l["category"],
            content=l["content"],
            confidence=l["confidence"],
            source_task_id=l["source_task_id"],
        )

    log.info(f"Extracted {len(learnings)} learnings from task {task_id}")
    return learnings
