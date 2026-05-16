"""Permission checker — tier-based tool execution gating (REQ-03).

Enforces four permission tiers:
- NOTHING: no tool use allowed
- ASK: human approves per tool (cached per session)
- SCOPED: tools within allowlist + path boundaries
- AUTOPILOT: everything allowed

Additionally, a hardcoded-never layer (REQ-03.7) sits ABOVE the tier system,
blocking destructive/irreversible actions regardless of the active tier.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from logger_python import get_logger

__all__ = [
    "AuditEntry",
    "HARDCODED_NEVER",
    "PermissionChecker",
    "PermissionTier",
    "PromptFn",
]

logger = get_logger(__name__)

PromptFn = Callable[[str, str, dict[str, Any]], bool]

# Keys in tool args that may contain filesystem paths.
_PATH_KEYS = ("path", "working_dir", "file", "directory")

# ---------------------------------------------------------------------------
# REQ-03.7: Hardcoded-never layer — destructive/irreversible actions blocked
# regardless of tier. Overridable only by explicit per-action flag.
# ---------------------------------------------------------------------------

HARDCODED_NEVER: list[dict[str, str]] = [
    # Git destructive operations
    {"tool": "shell", "pattern": r"\bgit\s+push\s+--force\b", "reason": "git push --force"},
    {"tool": "shell", "pattern": r"\bgit\s+push\s+-f\b", "reason": "git push --force (short flag)"},
    {"tool": "shell", "pattern": r"\bgit\s+reset\s+--hard\b", "reason": "git reset --hard"},
    {
        "tool": "shell",
        "pattern": r"\bgit\s+rebase\b.*\b(main|master)\b",
        "reason": "git rebase onto main/master",
    },
    {
        "tool": "shell",
        "pattern": r"\bgit\s+branch\s+-[dD]\s+(main|master)\b",
        "reason": "delete main/master branch",
    },
    # Filesystem destructive
    {"tool": "shell", "pattern": r"\brm\s+-rf\s+/", "reason": "rm -rf /"},
    {"tool": "shell", "pattern": r"\brm\s+-rf\s+~", "reason": "rm -rf ~"},
    {"tool": "shell", "pattern": r"\brm\s+-rf\s+\.\s*$", "reason": "rm -rf ."},
    # System destructive
    {"tool": "shell", "pattern": r"\bmkfs\b", "reason": "filesystem format (mkfs)"},
    {"tool": "shell", "pattern": r"\bdd\s+if=", "reason": "raw disk write (dd)"},
    {"tool": "shell", "pattern": r"\bsudo\s+rm\b", "reason": "sudo rm"},
    {
        "tool": "shell",
        "pattern": r":()\{\s*:\|:&\s*\};:",
        "reason": "fork bomb",
    },
]


class PermissionTier(str, Enum):
    """Permission levels from most restrictive to least."""

    NOTHING = "nothing"
    ASK = "ask"
    SCOPED = "scoped"
    AUTOPILOT = "autopilot"


@dataclass
class AuditEntry:
    """In-memory audit record of a permission check decision."""

    action: str
    tool: str
    agent_id: str
    status: str
    reason: str = ""


class PermissionChecker:
    """Gate tool execution based on the active permission tier.

    Args:
        tier: Active permission level.
        allowed_paths: Filesystem path prefixes allowed under SCOPED tier.
        allowed_tools: Tool names permitted under SCOPED tier.
        prompt_fn: Callback for ASK tier — receives (tool, agent_id, args).
    """

    def __init__(
        self,
        tier: PermissionTier,
        allowed_paths: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        prompt_fn: PromptFn | None = None,
        per_call: bool = False,
    ) -> None:
        self._tier = tier
        self._allowed_paths = allowed_paths or []
        self._allowed_tools = allowed_tools or []
        self._prompt_fn = prompt_fn
        self._per_call = per_call
        self._session_approvals: set[str] = set()
        self.audit_entries: list[AuditEntry] = []
        self.last_denial_reason: str = ""

    def check(self, tool_name: str, agent_id: str, args: dict[str, Any]) -> bool:
        """Return True if the tool call is permitted under the current tier.

        The hardcoded-never layer is evaluated FIRST — it blocks destructive
        actions regardless of tier unless explicitly overridden via
        ``allow_hardcoded_never``.
        """
        # REQ-03.7: hardcoded-never sits above all tiers
        allowed, reason = self.check_hardcoded_never(tool_name, args)
        if not allowed:
            self._record_audit("tool_blocked", tool_name, agent_id, "hardcoded_never", reason)
            self.last_denial_reason = reason
            return False

        if self._tier == PermissionTier.NOTHING:
            reason = "Tier 0 (NOTHING): all tool calls blocked"
            self._record_audit("tool_blocked", tool_name, agent_id, "tier_0_blocked", reason)
            self.last_denial_reason = reason
            return False

        if self._tier == PermissionTier.AUTOPILOT:
            self._record_audit("tool_call", tool_name, agent_id, "auto_permitted")
            return True

        if self._tier == PermissionTier.ASK:
            return self._check_ask(tool_name, agent_id, args)

        return self._check_scoped(tool_name, args)

    def _record_audit(
        self,
        action: str,
        tool: str,
        agent_id: str,
        status: str,
        reason: str = "",
    ) -> None:
        """Record an audit entry for a permission decision."""
        entry = AuditEntry(
            action=action, tool=tool, agent_id=agent_id,
            status=status, reason=reason,
        )
        self.audit_entries.append(entry)
        logger.debug("Permission audit: %s %s %s -> %s", action, tool, agent_id, status)

    def check_hardcoded_never(
        self, tool_name: str, args: dict[str, Any], *, allow_hardcoded_never: bool = False
    ) -> tuple[bool, str]:
        """Check against hardcoded-never rules (REQ-03.7).

        Args:
            tool_name: The tool being invoked (e.g. "shell").
            args: Tool arguments — for shell, expects a "command" or "cmd" key.
            allow_hardcoded_never: Explicit per-action override flag. When True,
                bypasses the hardcoded-never layer entirely.

        Returns:
            (True, "") if allowed, (False, reason) if blocked.
        """
        if allow_hardcoded_never:
            return (True, "")

        for rule in HARDCODED_NEVER:
            if rule["tool"] != tool_name:
                continue
            command = args.get("command") or args.get("cmd") or ""
            if not command:
                continue
            if re.search(rule["pattern"], command):
                reason = (
                    f"Hardcoded-never: '{rule['reason']}' is blocked as a "
                    f"destructive/irreversible action (REQ-03.7)"
                )
                return (False, reason)

        return (True, "")

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

    def _check_ask(self, tool_name: str, agent_id: str, args: dict[str, Any]) -> bool:
        """ASK tier: prompt once per tool name, cache approval.

        When per_call mode is enabled, the session cache is bypassed
        and every invocation triggers the prompt callback.
        """
        if not self._per_call and tool_name in self._session_approvals:
            return True

        if self._prompt_fn is None:
            return False

        approved = self._prompt_fn(tool_name, agent_id, args)
        if approved:
            self._session_approvals.add(tool_name)
        return approved

    def _check_scoped(self, tool_name: str, args: dict[str, Any]) -> bool:
        """SCOPED tier: tool must be in allowlist; paths must be in bounds."""
        if tool_name not in self._allowed_tools:
            self.last_denial_reason = (
                f"Tool '{tool_name}' not in allowed tools: {self._allowed_tools}"
            )
            return False

        paths = self._extract_paths(args)

        if not paths:
            return True

        for p in paths:
            if not self._path_in_bounds(p):
                self.last_denial_reason = (
                    f"Path '{p}' is outside allowed boundaries: {self._allowed_paths}"
                )
                return False
        return True

    def _extract_paths(self, args: dict[str, Any]) -> list[str]:
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
            if resolved == allowed_path:
                return True
            try:
                resolved.relative_to(allowed_path)
                return True
            except ValueError:
                continue
        return False
