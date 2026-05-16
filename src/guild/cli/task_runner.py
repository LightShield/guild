"""Task and chat execution logic for the Guild CLI.

Contains the core agent loop creation, task execution, learning injection,
and result persistence — extracted from the CLI layer for separation of
concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from logger_python import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from guild.agent.loop import AgentLoop
    from guild.config.models import GuildConfig
    from guild.provider.base import LLMProvider
    from guild.storage.sqlite import Storage

from guild.agent.loop import DEFAULT_MAX_TURNS
from guild.agent.prompts import GUILD_MASTER_PROMPT
from guild.config.constants import (
    AGENT_ID_PREFIX_LEN,
    MAX_TURNS_CAP,
    MIN_TURNS,
    SECONDS_PER_TURN_ESTIMATE,
)
from guild.config.loader import DB_FILENAME
from guild.task.spec import TaskStatus

__all__ = [
    "AGENT_ID_PREFIX_LEN",
    "GUILD_MASTER_PROMPT",
    "OLLAMA_PROVIDER_NAME",
    "build_system_prompt_with_learnings",
    "compute_max_turns",
    "create_chat_loop",
    "create_provider_for_backend",
    "create_resilient_provider",
    "create_task_agent_loop",
    "extract_post_task_learnings",
    "persist_task_result",
    "run_task",
    "run_team_task",
]

logger = get_logger(__name__)

OLLAMA_PROVIDER_NAME = "ollama"


def _parse_escalation_config(config: GuildConfig) -> tuple[list[str], list[str]]:
    """Extract escalation chain models and CLI tool names from config."""
    chain_models = [m.strip() for m in config.escalation_chain.split(",") if m.strip()]
    cli_tools = [t.strip() for t in config.escalation_cli_providers.split(",") if t.strip()]
    return chain_models, cli_tools


def create_provider_for_backend(provider_name: str, base_url: str, model: str) -> LLMProvider:
    """Create an LLM provider by name, dispatching to the correct backend."""
    if provider_name == OLLAMA_PROVIDER_NAME:
        from guild.provider.ollama import create_provider

        return create_provider(base_url, model)
    raise ValueError(f"Unknown provider: {provider_name}")


def create_chat_loop(config: GuildConfig, working_dir: str, permission: str) -> AgentLoop:
    """Create an AgentLoop instance for interactive chat (REQ-06.9)."""
    from guild.agent.loop import AgentLoop
    from guild.permissions.checker import PermissionChecker, PermissionTier
    from guild.tools.registry import build_tool_executors

    PermissionTier(permission)  # fail fast on invalid permission tier

    provider = create_provider_for_backend(config.provider_name, config.base_url, config.model)
    tool_executors = build_tool_executors()

    tier = PermissionTier(permission)
    _checker = PermissionChecker(tier=tier)

    return AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=DEFAULT_MAX_TURNS,
    )


def create_resilient_provider(config: GuildConfig) -> LLMProvider:
    """Build an LLM provider, with escalation chain and retry if configured."""
    from guild.provider.escalation import EscalatingProvider, EscalationChain
    from guild.provider.retry import RetryProvider

    if not config.provider_name:
        raise ValueError("provider_name must be configured")

    primary = create_provider_for_backend(config.provider_name, config.base_url, config.model)

    chain_models, cli_tools = _parse_escalation_config(config)

    if not chain_models and not cli_tools:
        return RetryProvider(primary)

    providers = [primary]  # pragma: no cover — requires escalation chain config
    for model_name in chain_models:
        if model_name != config.model:
            providers.append(
                create_provider_for_backend(config.provider_name, config.base_url, model_name)
            )

    if cli_tools:
        from guild.provider.cli_provider import CLIToolProvider

        for tool_cmd in cli_tools:
            providers.append(CLIToolProvider(command=tool_cmd))

    chain = EscalationChain(providers)
    return RetryProvider(EscalatingProvider(chain))


def compute_max_turns(timeout: int) -> int:
    """Convert a timeout in seconds to a max turn count."""
    if timeout <= 0:
        return DEFAULT_MAX_TURNS
    return min(max(timeout // SECONDS_PER_TURN_ESTIMATE, MIN_TURNS), MAX_TURNS_CAP)


def create_task_agent_loop(config: GuildConfig, working_dir: str, timeout: int) -> AgentLoop:
    """Build an AgentLoop configured for task execution."""
    from guild.agent.loop import AgentLoop
    from guild.agent.stuck import StuckDetector
    from guild.tools.registry import build_tool_executors

    provider = create_resilient_provider(config)
    tool_executors = build_tool_executors()

    max_turns = compute_max_turns(timeout)
    stuck_detector = StuckDetector(
        max_repeated_errors=config.stuck_max_repeated_errors,
        max_no_progress_turns=config.stuck_max_no_progress_turns,
        max_repeated_calls=config.stuck_max_repeated_calls,
    )

    return AgentLoop(
        provider=provider,
        tool_executors=tool_executors,
        working_dir=working_dir,
        max_turns=max_turns,
        stuck_detector=stuck_detector,
    )


async def run_task(
    config: GuildConfig,
    working_dir: str,
    description: str,
    permission: str,
    timeout: int,
    guild_dir: Path,
) -> str:
    """Execute a task through the agent loop."""
    from guild.permissions.checker import PermissionTier
    from guild.storage.sqlite import Storage

    if not description or not description.strip():
        raise ValueError("Task description cannot be empty")
    PermissionTier(permission)  # raises ValueError if invalid

    db_path = guild_dir / DB_FILENAME
    async with Storage(db_path) as store:
        loop = create_task_agent_loop(config, working_dir, timeout)
        system_prompt = await build_system_prompt_with_learnings(store)
        result = await loop.run(system_prompt, description)
        await persist_task_result(store, loop, description, result, config)
        await extract_post_task_learnings(store, loop, config)

    return result


async def build_system_prompt_with_learnings(store: Storage) -> str:
    """Build the system prompt, injecting high-confidence learnings (REQ-09.4)."""
    system_prompt = GUILD_MASTER_PROMPT
    try:
        from guild.agent.learning import MIN_INJECTION_CONFIDENCE, format_learnings_for_injection

        existing_learnings = await store.list_learnings(min_confidence=MIN_INJECTION_CONFIDENCE)
        injection = format_learnings_for_injection(existing_learnings)
        if injection:
            system_prompt = f"{system_prompt}\n\n{injection}"
    except (ImportError, OSError, ValueError):  # pragma: no cover
        logger.debug("Learning injection failed (non-critical)", exc_info=True)
    return system_prompt


def _generate_task_ids(task_id: str) -> tuple[str, str]:
    """Generate a task ID and its associated agent ID."""
    agent_id = f"guild-master-{task_id[:AGENT_ID_PREFIX_LEN]}"
    return task_id, agent_id


def _format_audit_details(task_id: str, loop: AgentLoop) -> str:
    """Build the audit log details string for a completed task."""
    return (
        f"task={task_id} tokens_in={loop.total_input_tokens}"
        f" tokens_out={loop.total_output_tokens}"
    )


async def persist_task_result(
    store: Storage, loop: AgentLoop, description: str, result: str, config: GuildConfig
) -> None:
    """Save task, agent, messages, and audit entry to storage."""
    import uuid

    task_id, agent_id = _generate_task_ids(str(uuid.uuid4()))

    await store.create_task(task_id, description)
    await store.update_task(
        task_id, status=TaskStatus.COMPLETED, result=result, assigned_agent=agent_id
    )
    await store.register_agent(agent_id, "master")
    await store.update_agent(
        agent_id,
        token_input=str(loop.total_input_tokens),
        token_output=str(loop.total_output_tokens),
    )

    for msg in loop.messages:
        if msg.role and msg.content:
            await store.append_message(agent_id, msg.role, msg.content)

    await store.log_audit(
        action="task_completed",
        agent_id=agent_id,
        details=_format_audit_details(task_id, loop),
    )


async def extract_post_task_learnings(
    store: Storage, loop: AgentLoop, config: GuildConfig
) -> None:  # pragma: no cover — requires LLM for extraction
    """Extract learnings from the completed task (REQ-09.1)."""
    try:
        from guild.agent.learning import extract_learnings

        provider = create_resilient_provider(config)
        tasks = await store.list_tasks()
        if tasks:
            task_id = tasks[-1].get("task_id", "")
            await extract_learnings(task_id, store, provider)
    except (ImportError, OSError, ValueError):
        logger.debug("Learning extraction failed (non-critical)", exc_info=True)


async def run_team_task(
    config: GuildConfig,
    working_dir: str,
    guild_dir: Path,
    team_name: str,
    description: str,
) -> str:
    """Run a task through a multi-agent team composition."""
    from guild.blocks.registry import BlockRegistry
    from guild.orchestration.team_runner import TeamRunner
    from guild.storage.sqlite import Storage

    db_path = guild_dir / DB_FILENAME
    async with Storage(db_path) as store:
        registry = BlockRegistry()
        registry.load_from_dir(guild_dir / "blocks")

        team_def = registry.get_team(team_name)
        if team_def is None:
            raise ValueError(f"Team '{team_name}' not found in {guild_dir / 'blocks'}")

        provider = create_resilient_provider(config)
        runner = TeamRunner(
            team=team_def,
            registry=registry,
            provider=provider,
            storage=store,
            working_dir=working_dir,
        )
        result = await runner.run(description)
    return result
