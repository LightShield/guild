"""Permission enforcement for tool execution.

Implements the 4-tier permission system: nothing, ask, scoped, autopilot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from guild.core.models import PermissionTier

__all__ = ["PermissionChecker"]

PromptFn = Callable[[str, str, dict], bool]


def _default_prompt(tool_name: str, agent_id: str, args: dict) -> bool:
    """Default interactive prompt for the ASK tier.

    Args:
        tool_name: Name of the tool being requested.
        agent_id: ID of the requesting agent.
        args: Tool call arguments.

    Returns:
        True if the user approves the tool call.
    """
    import json
    import logging

    logging.info(f"Agent [{agent_id}] wants to use tool: {tool_name}")
    logging.info(f"Args: {json.dumps(args, indent=2)[:500]}")
    resp = input("   Allow? [y]es / [n]o / [a]lways this tool: ").strip().lower()
    return resp in ("y", "yes", "a", "always")


class PermissionChecker:
    """Checks whether an agent is allowed to execute a tool call.

    Args:
        tier: Permission tier to enforce.
        allowed_paths: Directories the agent can access (scoped tier).
        allowed_tools: Tool names the agent can use (scoped tier).
        prompt_fn: Callable for interactive approval (ask tier).
    """

    def __init__(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        prompt_fn: PromptFn | None = None,
    ) -> None:
        self.tier = tier
        self.allowed_paths = [Path(p).resolve() for p in (allowed_paths or [])]
        self.allowed_tools = set(allowed_tools) if allowed_tools else None
        self.prompt_fn = prompt_fn or _default_prompt
        self._session_approvals: set[str] = set()

    def get_tier(self) -> PermissionTier:
        """Get the current permission tier.

        Returns:
            Current PermissionTier.
        """
        return self.tier

    def set_tier(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
    ) -> None:
        """Switch permission tier at runtime.

        Clears session approvals on tier change.

        Args:
            tier: New permission tier.
            allowed_paths: New allowed paths (for scoped tier).
            allowed_tools: New allowed tools (for scoped tier).
        """
        self.tier = tier
        self._session_approvals.clear()
        if allowed_paths is not None:
            self.allowed_paths = [Path(p).resolve() for p in allowed_paths]
        if allowed_tools is not None:
            self.allowed_tools = set(allowed_tools)

    def check(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """Check if a tool call is allowed.

        Args:
            tool_name: Name of the tool.
            agent_id: ID of the requesting agent.
            args: Tool call arguments.

        Returns:
            True if the call is permitted.
        """
        if self.tier == PermissionTier.NOTHING:
            return False
        if self.tier == PermissionTier.AUTOPILOT:
            return True
        if self.tier == PermissionTier.ASK:
            return self._check_ask(tool_name, agent_id, args)
        if self.tier == PermissionTier.SCOPED:
            return self._check_scope(tool_name, args)
        return False

    def _check_ask(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """Ask tier: prompt user, remember session approvals."""
        if tool_name in self._session_approvals:
            return True
        result = self.prompt_fn(tool_name, agent_id, args)
        if result:
            self._session_approvals.add(tool_name)
        return result

    def _check_scope(self, tool_name: str, args: dict) -> bool:
        """Scoped tier: check tool allowlist and path boundaries."""
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return False
        for key in ("path", "working_dir"):
            if key in args and args[key] and self.allowed_paths:
                target = Path(args[key]).resolve()
                if not any(_is_under(target, ap) for ap in self.allowed_paths):
                    return False
        return True


def _is_under(path: Path, parent: Path) -> bool:
    """Check if path is under parent directory.

    Args:
        path: Path to check.
        parent: Parent directory.

    Returns:
        True if path is under parent.
    """
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
