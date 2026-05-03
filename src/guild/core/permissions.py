"""Permission enforcement for tool execution."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from guild.core.models import PermissionTier


class PermissionDenied(Exception):
    """Raised when a tool call is denied by the permission system."""


class PermissionChecker:
    """Checks whether an agent is allowed to execute a tool call.

    Tiers:
      nothing  — no tool use at all
      ask      — prompt user for approval (once / per-session / per-call)
      scoped   — allowed within a defined scope (directory tree, tool set)
      autopilot — everything allowed
    """

    def __init__(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        prompt_fn: Callable[[str, str, dict], bool] | None = None,
    ):
        self.tier = tier
        self.allowed_paths = [Path(p).resolve() for p in (allowed_paths or [])]
        self.allowed_tools = set(allowed_tools) if allowed_tools else None
        self.prompt_fn = prompt_fn or self._default_prompt
        self._session_approvals: set[str] = set()

    @staticmethod
    def _default_prompt(tool_name: str, agent_id: str, args: dict) -> bool:
        """Default interactive prompt for ask tier."""
        import json
        print(f"\n🔒 Agent [{agent_id}] wants to use tool: {tool_name}")
        print(f"   Args: {json.dumps(args, indent=2)[:500]}")
        resp = input("   Allow? [y]es / [n]o / [a]lways this tool: ").strip().lower()
        return resp in ("y", "yes", "a", "always")

    def _check_ask(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """Ask tier: prompt user, remember session approvals."""
        if tool_name in self._session_approvals:
            return True
        import json
        print(f"\n🔒 Agent [{agent_id}] wants to use tool: {tool_name}")
        print(f"   Args: {json.dumps(args, indent=2)[:500]}")
        resp = input("   Allow? [y]es / [n]o / [a]lways this tool: ").strip().lower()
        if resp in ("a", "always"):
            self._session_approvals.add(tool_name)
            return True
        return resp in ("y", "yes")

    def _check_scope(self, tool_name: str, args: dict) -> bool:
        """Scoped tier: check tool allowlist and path boundaries."""
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return False
        # Check path-based args against allowed paths
        for key in ("path", "working_dir"):
            if key in args and args[key] and self.allowed_paths:
                target = Path(args[key]).resolve()
                if not any(self._is_under(target, ap) for ap in self.allowed_paths):
                    return False
        return True

    @staticmethod
    def _is_under(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def check(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """Check if a tool call is allowed. Returns True/False."""
        if self.tier == PermissionTier.NOTHING:
            return False
        if self.tier == PermissionTier.AUTOPILOT:
            return True
        if self.tier == PermissionTier.ASK:
            return self._check_ask(tool_name, agent_id, args)
        if self.tier == PermissionTier.SCOPED:
            return self._check_scope(tool_name, args)
        return False
