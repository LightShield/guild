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
