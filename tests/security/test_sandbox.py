"""Tests for security/sandbox.py — sandboxed execution and secret management (REQ-13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from guild.security.sandbox import SandboxPolicy, load_sandbox_policy

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# REQ-13.4: File system boundaries — agents can only access allowed paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-13.4")
class TestCheckPath:
    """Path boundary enforcement for agent file access."""

    def test_check_path_allows_within_boundary(self) -> None:
        """Path inside an allowed directory is permitted."""
        policy = SandboxPolicy(allowed_paths=["/home/user/project"])
        allowed, reason = policy.check_path("/home/user/project/src/main.py")
        assert allowed is True
        assert reason == ""

    def test_check_path_blocks_outside_boundary(self) -> None:
        """Path outside all allowed directories is denied."""
        policy = SandboxPolicy(allowed_paths=["/home/user/project"])
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "outside all allowed paths" in reason

    def test_check_path_blocks_denied_paths(self) -> None:
        """Denied paths take precedence over allowed paths."""
        policy = SandboxPolicy(
            allowed_paths=["/home/user/project"],
            denied_paths=["/home/user/project/.env"],
        )
        allowed, reason = policy.check_path("/home/user/project/.env")
        assert allowed is False
        assert "denied path" in reason

    def test_check_path_handles_relative_paths(self, tmp_path: Path) -> None:
        """Relative paths are resolved against cwd before checking."""
        # Use tmp_path as the allowed directory and create a file within it
        policy = SandboxPolicy(allowed_paths=[str(tmp_path)])
        # A relative path that resolves to within tmp_path when cwd is tmp_path
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            allowed, reason = policy.check_path("subdir/file.txt")
            assert allowed is True
        finally:
            os.chdir(original_cwd)

    def test_check_path_allows_all_when_no_boundaries(self) -> None:
        """When no allowed_paths configured, all paths are accessible."""
        policy = SandboxPolicy()
        allowed, reason = policy.check_path("/any/path/at/all")
        assert allowed is True
        assert reason == ""

    def test_check_path_exact_match(self) -> None:
        """Path that exactly matches an allowed path is permitted."""
        policy = SandboxPolicy(allowed_paths=["/home/user/project"])
        allowed, reason = policy.check_path("/home/user/project")
        assert allowed is True


# ---------------------------------------------------------------------------
# REQ-13.5: Command allowlist/denylist
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-13.5")
class TestCheckCommand:
    """Command filtering via allowlist and denylist."""

    def test_check_command_allows_safe_command(self) -> None:
        """Command not in denylist is allowed when no allowlist configured."""
        policy = SandboxPolicy()
        allowed, reason = policy.check_command("ls -la")
        assert allowed is True
        assert reason == ""

    def test_check_command_blocks_denied_command(self) -> None:
        """Command in denylist is blocked."""
        policy = SandboxPolicy(denied_commands=["rm", "mkfs"])
        allowed, reason = policy.check_command("rm -rf /tmp/stuff")
        assert allowed is False
        assert "denylist" in reason

    def test_check_command_allowlist_restricts(self) -> None:
        """When allowlist is set, only listed commands are permitted."""
        policy = SandboxPolicy(allowed_commands=["ls", "cat", "grep"])
        allowed, reason = policy.check_command("ls -la /tmp")
        assert allowed is True

        allowed, reason = policy.check_command("rm file.txt")
        assert allowed is False
        assert "not in allowlist" in reason

    def test_check_command_denylist_overrides_allowlist(self) -> None:
        """Denylist takes precedence even if command is in allowlist."""
        policy = SandboxPolicy(
            allowed_commands=["curl", "wget"],
            denied_commands=["curl"],
        )
        allowed, reason = policy.check_command("curl http://example.com")
        assert allowed is False
        assert "denylist" in reason

    def test_check_command_handles_sudo_prefix(self) -> None:
        """Commands prefixed with sudo are correctly identified."""
        policy = SandboxPolicy(denied_commands=["rm"])
        allowed, reason = policy.check_command("sudo rm -rf /tmp/stuff")
        assert allowed is False


# ---------------------------------------------------------------------------
# REQ-13.2: Network access controls per agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-13.2")
class TestNetworkControls:
    """Network access policy enforcement."""

    def test_network_allowed_default_true(self) -> None:
        """By default, network access is allowed."""
        policy = SandboxPolicy()
        assert policy.network_allowed is True

    def test_network_can_be_disabled(self) -> None:
        """Network access can be completely disabled."""
        policy = SandboxPolicy(network_allowed=False)
        assert policy.network_allowed is False

    def test_network_hosts_allowlist_restricts(self) -> None:
        """When hosts allowlist is set, only those hosts are accessible."""
        policy = SandboxPolicy(network_hosts_allowlist=["api.github.com", "pypi.org"])
        assert "api.github.com" in policy.network_hosts_allowlist
        assert "pypi.org" in policy.network_hosts_allowlist
        assert "evil.com" not in policy.network_hosts_allowlist

    def test_network_hosts_empty_means_all_allowed(self) -> None:
        """Empty hosts allowlist means no host restriction."""
        policy = SandboxPolicy(network_hosts_allowlist=[])
        assert policy.network_hosts_allowlist == []
        # Interpretation: empty list = all hosts allowed (no restriction)


# ---------------------------------------------------------------------------
# REQ-13.3: Secret management — agents use API keys without seeing raw values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-13.3")
class TestSecretManagement:
    """Secret injection and masking for agent isolation."""

    def test_mask_secrets_replaces_values(self) -> None:
        """Secret values in text are replaced with [REDACTED:name]."""
        policy = SandboxPolicy(secrets={"API_KEY": "sk-abc123"})
        masked = policy.mask_secrets("Authorization: Bearer sk-abc123")
        assert "sk-abc123" not in masked
        assert "[REDACTED:API_KEY]" in masked

    def test_mask_secrets_handles_multiple(self) -> None:
        """Multiple secrets are all masked in a single pass."""
        policy = SandboxPolicy(
            secrets={
                "DB_PASSWORD": "hunter2",
                "API_TOKEN": "tok-xyz789",
            }
        )
        text = "Connecting with hunter2 and token tok-xyz789"
        masked = policy.mask_secrets(text)
        assert "hunter2" not in masked
        assert "tok-xyz789" not in masked
        assert "[REDACTED:DB_PASSWORD]" in masked
        assert "[REDACTED:API_TOKEN]" in masked

    def test_mask_secrets_no_secrets_returns_unchanged(self) -> None:
        """When no secrets configured, text passes through unchanged."""
        policy = SandboxPolicy()
        text = "Some normal text"
        assert policy.mask_secrets(text) == text

    def test_inject_secret_replaces_placeholders(self) -> None:
        """${SECRET_NAME} placeholders are replaced with actual values."""
        policy = SandboxPolicy(secrets={"API_KEY": "sk-abc123"})
        result = policy.inject_secret("curl -H 'Auth: ${API_KEY}' http://api.com")
        assert result == "curl -H 'Auth: sk-abc123' http://api.com"

    def test_inject_secret_leaves_unknown_placeholders(self) -> None:
        """Placeholders not in secrets dict are left unchanged."""
        policy = SandboxPolicy(secrets={"API_KEY": "sk-abc123"})
        result = policy.inject_secret("echo ${UNKNOWN_VAR} and ${API_KEY}")
        assert "${UNKNOWN_VAR}" in result
        assert "sk-abc123" in result

    def test_inject_secret_multiple_placeholders(self) -> None:
        """Multiple placeholders in one command are all resolved."""
        policy = SandboxPolicy(secrets={"USER": "admin", "PASS": "secret123"})
        result = policy.inject_secret("login ${USER} ${PASS}")
        assert result == "login admin secret123"


# ---------------------------------------------------------------------------
# REQ-13.1: Sandboxed execution — load policy from config
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.req("REQ-13.1")
class TestLoadSandboxPolicy:
    """Loading sandbox policy from .guild/security.toml."""

    def test_load_sandbox_policy_from_toml(self, tmp_path: Path) -> None:
        """Policy is correctly loaded from a security.toml file."""
        toml_content = """\
[filesystem]
allowed_paths = ["/home/user/project", "/tmp"]
denied_paths = ["/home/user/project/.env"]

[commands]
allow = ["ls", "cat", "grep", "git"]
deny = ["rm", "mkfs"]

[network]
allowed = true
hosts_allowlist = ["api.github.com", "pypi.org"]

[secrets]
API_KEY = "sk-test-12345"
DB_HOST = "localhost:5432"
"""
        config_file = tmp_path / "security.toml"
        config_file.write_text(toml_content)

        policy = load_sandbox_policy(tmp_path)

        assert policy.allowed_paths == ["/home/user/project", "/tmp"]
        assert policy.denied_paths == ["/home/user/project/.env"]
        assert policy.allowed_commands == ["ls", "cat", "grep", "git"]
        assert policy.denied_commands == ["rm", "mkfs"]
        assert policy.network_allowed is True
        assert policy.network_hosts_allowlist == ["api.github.com", "pypi.org"]
        assert policy.secrets == {"API_KEY": "sk-test-12345", "DB_HOST": "localhost:5432"}

    def test_load_sandbox_policy_defaults_when_missing(self, tmp_path: Path) -> None:
        """When no security.toml exists, returns a permissive default policy."""
        policy = load_sandbox_policy(tmp_path)

        assert policy.allowed_paths == []
        assert policy.denied_paths == []
        assert policy.allowed_commands == []
        assert policy.denied_commands == []
        assert policy.network_allowed is True
        assert policy.network_hosts_allowlist == []
        assert policy.secrets == {}

    def test_load_sandbox_policy_partial_config(self, tmp_path: Path) -> None:
        """Partial security.toml fills in defaults for missing sections."""
        toml_content = """\
[network]
allowed = false
"""
        config_file = tmp_path / "security.toml"
        config_file.write_text(toml_content)

        policy = load_sandbox_policy(tmp_path)

        assert policy.network_allowed is False
        # All other fields default
        assert policy.allowed_paths == []
        assert policy.denied_paths == []
        assert policy.allowed_commands == []
        assert policy.denied_commands == []
        assert policy.network_hosts_allowlist == []
        assert policy.secrets == {}


# ======================================================================
# Sandbox policy edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-13")
class TestSandboxEdgeCases:
    """Cover sandbox policy edge cases."""

    def test_resolve_path_returns_absolute(self) -> None:
        """_resolve_path returns an absolute resolved path."""
        policy = SandboxPolicy()
        result = policy._resolve_path("/tmp/normal")
        # On macOS, /tmp resolves to /private/tmp -- just check it\'s absolute
        assert result.is_absolute()
        assert "normal" in str(result)

    def test_extract_command_name_with_sudo(self) -> None:
        """_extract_command_name skips \'sudo\' prefix."""
        policy = SandboxPolicy()
        assert policy._extract_command_name("sudo rm -rf /tmp") == "rm"

    def test_extract_command_name_empty(self) -> None:
        """_extract_command_name returns empty for empty string."""
        policy = SandboxPolicy()
        assert policy._extract_command_name("") == ""

    def test_extract_command_name_only_prefixes(self) -> None:
        """_extract_command_name handles \'sudo env\' (all prefixes)."""
        policy = SandboxPolicy()
        # When idx >= len(parts), returns parts[-1]
        result = policy._extract_command_name("sudo env")
        assert result == "env"

    def test_load_sandbox_policy_from_file(self, tmp_path: Path) -> None:
        """load_sandbox_policy parses a security.toml file."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "security.toml").write_text(
            "[filesystem]\n"
            'allowed_paths = ["/tmp"]\n'
            'denied_paths = ["/etc"]\n'
            "\n"
            "[commands]\n"
            'allow = ["git", "ls"]\n'
            'deny = ["rm"]\n'
            "\n"
            "[network]\n"
            "allowed = false\n"
            'hosts_allowlist = ["api.example.com"]\n'
            "\n"
            "[secrets]\n"
            'API_KEY = "sk-secret-123"\n'
        )
        policy = load_sandbox_policy(guild_dir)
        assert policy.allowed_paths == ["/tmp"]
        assert policy.denied_paths == ["/etc"]
        assert policy.allowed_commands == ["git", "ls"]
        assert policy.denied_commands == ["rm"]
        assert policy.network_allowed is False
        assert policy.secrets["API_KEY"] == "sk-secret-123"

    def test_load_sandbox_policy_invalid_toml(self, tmp_path: Path) -> None:
        """load_sandbox_policy returns default on parse failure."""
        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "security.toml").write_text("invalid [[[toml")
        policy = load_sandbox_policy(guild_dir)
        # Should fall back to default (permissive)
        assert policy.allowed_paths == []
        assert policy.network_allowed is True

    def test_check_command_denylist_match(self) -> None:
        """Denied commands are blocked."""
        policy = SandboxPolicy(denied_commands=["rm", "dd"])
        allowed, reason = policy.check_command("rm -rf /tmp/test")
        assert allowed is False
        assert "denylist" in reason

    def test_check_command_allowlist_no_match(self) -> None:
        """Commands not in allowlist are rejected."""
        policy = SandboxPolicy(allowed_commands=["git", "ls"])
        allowed, reason = policy.check_command("curl http://evil.com")
        assert allowed is False
        assert "not in allowlist" in reason

    def test_inject_secret_unknown_placeholder_left_alone(self) -> None:
        """Unknown ${PLACEHOLDER} is left as-is."""
        policy = SandboxPolicy(secrets={"API_KEY": "secret123"})
        result = policy.inject_secret("echo ${UNKNOWN_VAR}")
        assert "${UNKNOWN_VAR}" in result

    def test_check_path_denied_takes_precedence(self) -> None:
        """Denied paths take precedence over allowed paths."""
        policy = SandboxPolicy(
            allowed_paths=["/tmp"],
            denied_paths=["/tmp/secret"],
        )
        allowed, reason = policy.check_path("/tmp/secret/file.txt")
        assert allowed is False

    def test_check_path_outside_allowed(self) -> None:
        """Paths outside allowed_paths are rejected."""
        policy = SandboxPolicy(allowed_paths=["/tmp"])
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "outside" in reason


# ======================================================================
# Security/sandbox additional edges (from coverage gaps)
# ======================================================================


@pytest.mark.req("REQ-13.4")
@pytest.mark.unit
class TestSandboxEdges:
    """Cover security/sandbox.py uncovered branches."""

    def test_check_path_denied_path_matches(self) -> None:
        """check_path returns False when path is in denied list (line 65->63)."""
        policy = SandboxPolicy(
            denied_paths=["/etc", "/var/secret"],
            allowed_paths=["/"],
        )
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "denied" in reason.lower()

    def test_check_command_denied_matches(self) -> None:
        """check_command returns False when command is in denylist (line 89->88)."""
        policy = SandboxPolicy(
            denied_commands=["rm", "shutdown"],
            allowed_commands=[],
        )
        allowed, reason = policy.check_command("rm -rf /")
        assert allowed is False
        assert "denylist" in reason.lower()

    def test_mask_secrets_replaces_value(self) -> None:
        """mask_secrets replaces matching secret values (line 108->107)."""
        policy = SandboxPolicy(
            secrets={"API_KEY": "sk-12345", "DB_PASS": "secret123"},
        )
        result = policy.mask_secrets("Token: sk-12345, Pass: secret123")
        assert "sk-12345" not in result
        assert "[REDACTED:API_KEY]" in result
        assert "[REDACTED:DB_PASS]" in result

    def test_resolve_path_oserror(self) -> None:
        """_resolve_path handles OSError gracefully (lines 135-136)."""
        from unittest.mock import patch

        policy = SandboxPolicy()
        # Mock Path.resolve() to raise OSError
        with patch("guild.security.sandbox.Path.resolve", side_effect=OSError("broken link")):
            result = policy._resolve_path("/some/broken/link")
            # Should return the unresolved path (line 136)
            assert result is not None

    def test_check_path_multiple_denied_second_matches(self) -> None:
        """check_path iterates through multiple denied paths (65->63 branch)."""
        policy = SandboxPolicy(
            denied_paths=["/safe/dir", "/etc/secrets"],
            allowed_paths=["/"],
        )
        # First denied path doesn\'t match, second does
        allowed, reason = policy.check_path("/etc/secrets/key")
        assert allowed is False

    def test_check_command_multiple_denied_second_matches(self) -> None:
        """check_command iterates through multiple denied commands (89->88)."""
        policy = SandboxPolicy(
            denied_commands=["safe_cmd", "rm"],
            allowed_commands=[],
        )
        # First denied doesn\'t match, second does
        allowed, reason = policy.check_command("rm -rf /")
        assert allowed is False

    def test_mask_secrets_multiple_secrets_some_match(self) -> None:
        """mask_secrets iterates through multiple secrets (108->107 branch)."""
        policy = SandboxPolicy(
            secrets={"NO_MATCH": "xyz_not_present", "MATCH": "secret123"},
        )
        result = policy.mask_secrets("The password is secret123")
        # First secret doesn\'t match, second does -- exercises loop continuation
        assert "secret123" not in result
        assert "[REDACTED:MATCH]" in result
