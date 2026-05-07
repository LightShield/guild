"""Permission checker — tier-based tool execution gating (REQ-03).

Enforces four permission tiers:
- NOTHING: no tool use allowed
- ASK: human approves per tool (cached per session)
- SCOPED: tools within allowlist + path boundaries
- AUTOPILOT: everything allowed
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import PurePosixPath

__all__ = ["PermissionChecker", "PermissionTier", "PromptFn"]

PromptFn = Callable[[str, str, dict], bool]

# Keys in tool args that may contain filesystem paths.
_PATH_KEYS = ("path", "working_dir", "file", "directory")


class PermissionTier(str, Enum):
    """Permission levels from most restrictive to least."""

    NOTHING = "nothing"
    ASK = "ask"
    SCOPED = "scoped"
    AUTOPILOT = "autopilot"


class PermissionChecker:
    """Gate tool execution based on the active permission tier.

    Parameters
    ----------
    tier:
        Active permission level.
    allowed_paths:
        Filesystem path prefixes allowed under SCOPED tier.
    allowed_tools:
        Tool names permitted under SCOPED tier.
    prompt_fn:
        Callback for ASK tier — receives (tool, agent_id, args).
    """

    def __init__(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        prompt_fn: PromptFn | None = None,
    ) -> None:
        self._tier = tier
        self._allowed_paths = allowed_paths or []
        self._allowed_tools = allowed_tools or []
        self._prompt_fn = prompt_fn
        self._session_approvals: set[str] = set()

    def check(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """Return True if the tool call is permitted under the current tier."""
        if self._tier == PermissionTier.NOTHING:
            return False

        if self._tier == PermissionTier.AUTOPILOT:
            return True

        if self._tier == PermissionTier.ASK:
            return self._check_ask(tool_name, agent_id, args)

        # SCOPED
        return self._check_scoped(tool_name, args)

    def set_tier(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        prompt_fn: PromptFn | None = None,
    ) -> None:
        """Switch the active tier at runtime, clearing session state."""
        self._tier = tier
        self._session_approvals = set()

        if allowed_paths is not None:
            self._allowed_paths = allowed_paths
        if allowed_tools is not None:
            self._allowed_tools = allowed_tools
        if prompt_fn is not None:
            self._prompt_fn = prompt_fn

    def _check_ask(self, tool_name: str, agent_id: str, args: dict) -> bool:
        """ASK tier: prompt once per tool name, cache approval."""
        if tool_name in self._session_approvals:
            return True

        if self._prompt_fn is None:
            return False

        approved = self._prompt_fn(tool_name, agent_id, args)
        if approved:
            self._session_approvals.add(tool_name)
        return approved

    def _check_scoped(self, tool_name: str, args: dict) -> bool:
        """SCOPED tier: tool must be in allowlist; paths must be in bounds."""
        if tool_name not in self._allowed_tools:
            return False

        # Extract any path arguments from args
        paths = self._extract_paths(args)

        # If no paths in args, allow (tool is in allowlist)
        if not paths:
            return True

        # All paths must be within at least one allowed path prefix
        return all(self._path_in_bounds(p) for p in paths)

    def _extract_paths(self, args: dict) -> list[str]:
        """Pull filesystem paths from tool arguments."""
        paths: list[str] = []
        for key in _PATH_KEYS:
            if key in args and isinstance(args[key], str):
                paths.append(args[key])
        return paths

    def _path_in_bounds(self, path: str) -> bool:
        """Check if a path falls within any allowed path prefix."""
        resolved = PurePosixPath(path)
        for allowed in self._allowed_paths:
            allowed_path = PurePosixPath(allowed)
            # Check if path starts with the allowed prefix
            if resolved == allowed_path:
                return True
            try:
                resolved.relative_to(allowed_path)
                return True
            except ValueError:
                continue
        return False
