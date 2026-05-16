"""Sandbox policy — path boundaries, command filtering, network controls, secrets (REQ-13).

Provides a declarative security policy for agent execution:
- REQ-13.1: Sandboxed execution for shell commands
- REQ-13.2: Network access controls per agent
- REQ-13.3: Secret management — agents use API keys without seeing raw values
- REQ-13.4: File system boundaries — agents can only access allowed paths
- REQ-13.5: Command allowlist/denylist
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from guild.config.constants import SECURITY_FILENAME
from logger_python import get_logger

__all__ = ["SandboxPolicy", "load_sandbox_policy"]

logger = get_logger(__name__)

_SECRET_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


@dataclass
class SandboxPolicy:
    """Security policy for agent execution.

    Attributes:
        allowed_paths: Filesystem path prefixes the agent may access. Empty = no restriction.
        denied_paths: Filesystem paths explicitly blocked (takes precedence over allowed).
        allowed_commands: Shell commands permitted. Empty list = all allowed (minus denylist).
        denied_commands: Shell commands explicitly blocked (takes precedence over allowlist).
        network_allowed: Whether network access is permitted at all.
        network_hosts_allowlist: Specific hosts the agent may contact. Empty = all hosts allowed.
        secrets: Named secrets (name -> value). Injected into commands, never shown.
    """

    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(default_factory=list)
    network_allowed: bool = True
    network_hosts_allowlist: list[str] = field(default_factory=list)
    secrets: dict[str, str] = field(default_factory=dict)

    def check_path(self, path: str) -> tuple[bool, str]:
        """Check if a path is allowed under this policy.

        Returns (allowed, reason). Denied paths take precedence over allowed.
        """
        resolved = self._resolve_path(path)

        for denied in self.denied_paths:
            denied_resolved = self._resolve_path(denied)
            if self._is_subpath(resolved, denied_resolved):
                return (False, f"Path '{path}' is within denied path '{denied}'")

        if not self.allowed_paths:
            return (True, "")

        for allowed in self.allowed_paths:
            allowed_resolved = self._resolve_path(allowed)
            if self._is_subpath(resolved, allowed_resolved):
                return (True, "")

        return (False, f"Path '{path}' is outside all allowed paths")

    def check_command(self, command: str) -> tuple[bool, str]:
        """Check if a shell command is allowed under this policy.

        Returns (allowed, reason). Denied commands take precedence.
        """
        cmd_name = self._extract_command_name(command)

        for denied in self.denied_commands:
            if self._command_matches(command, cmd_name, denied):
                return (False, f"Command '{cmd_name}' is in denylist")

        if self.allowed_commands:
            for allowed in self.allowed_commands:
                if self._command_matches(command, cmd_name, allowed):
                    return (True, "")
            return (False, f"Command '{cmd_name}' is not in allowlist")

        return (True, "")

    def mask_secrets(self, text: str) -> str:
        """Replace secret values with [REDACTED:name] in text.

        Prevents secret leakage in logs, agent messages, and tool output.
        """
        result = text
        for name, value in self.secrets.items():
            if value and value in result:
                result = result.replace(value, f"[REDACTED:{name}]")
        return result

    def inject_secret(self, command: str) -> str:
        """Replace ${SECRET_NAME} placeholders with actual values for execution.

        Unknown placeholders are left as-is so the shell can resolve them
        or they fail visibly rather than silently becoming empty.
        """

        def _replacer(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in self.secrets:
                return self.secrets[name]
            return match.group(0)  # Leave unknown placeholders unchanged

        return _SECRET_PLACEHOLDER_RE.sub(_replacer, command)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path to absolute form for comparison."""
        p = Path(path)
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            return p.resolve()
        except (OSError, ValueError):
            return p

    def _is_subpath(self, child: Path, parent: Path) -> bool:
        """Check if child path is equal to or under parent path."""
        if child == parent:
            return True
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def _extract_command_name(self, command: str) -> str:
        """Extract the base command name from a full command string."""
        stripped = command.strip()
        parts = stripped.split()
        if not parts:
            return ""
        idx = 0
        while idx < len(parts) and parts[idx] in ("sudo", "env"):
            idx += 1
        if idx >= len(parts):
            return parts[-1] if parts else ""
        return parts[idx]

    def _command_matches(self, full_cmd: str, cmd_name: str, pattern: str) -> bool:
        """Check if a command matches a pattern (name or regex)."""
        if cmd_name == pattern:
            return True
        return bool(re.search(rf"\b{re.escape(pattern)}\b", full_cmd))


def load_sandbox_policy(guild_dir: Path) -> SandboxPolicy:
    """Load sandbox policy from .guild/security.toml if it exists.

    Falls back to a permissive default policy when no config file is present.
    """
    config_path = guild_dir / SECURITY_FILENAME

    if not config_path.exists():
        logger.debug("No security.toml found at %s, using default policy", config_path)
        return SandboxPolicy()

    return _parse_security_toml(config_path)


def _parse_security_toml(config_path: Path) -> SandboxPolicy:
    """Parse a security.toml file into a SandboxPolicy."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python 3.10 compat
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning("Failed to parse %s: %s — using default policy", config_path, e)
        return SandboxPolicy()

    fs = data.get("filesystem", {})
    commands = data.get("commands", {})
    network = data.get("network", {})
    secrets = data.get("secrets", {})

    return SandboxPolicy(
        allowed_paths=fs.get("allowed_paths", []),
        denied_paths=fs.get("denied_paths", []),
        allowed_commands=commands.get("allow", []),
        denied_commands=commands.get("deny", []),
        network_allowed=network.get("allowed", True),
        network_hosts_allowlist=network.get("hosts_allowlist", []),
        secrets=secrets,
    )
