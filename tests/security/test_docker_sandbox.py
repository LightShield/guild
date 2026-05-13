"""Tests for security/docker_sandbox.py — Docker sandbox pure logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from guild.security.docker_sandbox import DockerSandbox, is_docker_available


@pytest.mark.unit
class TestDockerSandboxInit:
    """DockerSandbox __init__ stores configuration."""

    def test_defaults(self) -> None:
        """DockerSandbox uses default image, no network, default timeout."""
        sandbox = DockerSandbox()
        assert sandbox.network is False
        assert "python" in sandbox.image or "guild" in sandbox.image or sandbox.image != ""
        assert sandbox.timeout > 0

    def test_custom_params(self) -> None:
        """DockerSandbox respects custom image, network, and timeout."""
        sandbox = DockerSandbox(image="alpine:latest", network=True, timeout=120.0)
        assert sandbox.image == "alpine:latest"
        assert sandbox.network is True
        assert sandbox.timeout == 120.0


@pytest.mark.unit
class TestBuildDockerArgs:
    """DockerSandbox._build_docker_args produces correct argument list."""

    def test_basic_args_without_network(self) -> None:
        """Without network, --network=none is included."""
        sandbox = DockerSandbox(image="test-image", network=False, timeout=30.0)
        args = sandbox._build_docker_args("/workspace/project")

        assert args[0] == "docker"
        assert args[1] == "run"
        assert "--rm" in args
        assert "--network=none" in args
        assert "--security-opt=no-new-privileges" in args
        assert "test-image" in args
        # Volume mount
        assert any("/workspace/project:/workspace:rw" in a for a in args)

    def test_basic_args_with_network(self) -> None:
        """With network=True, --network=none is NOT included."""
        sandbox = DockerSandbox(image="test-image", network=True, timeout=30.0)
        args = sandbox._build_docker_args("/workspace/project")

        assert "--network=none" not in args
        assert "test-image" in args


@pytest.mark.unit
class TestIsDockerAvailable:
    """is_docker_available returns False when Docker CLI is not on PATH."""

    def test_returns_false_when_docker_not_on_path(self) -> None:
        """When shutil.which('docker') is None, returns False immediately."""
        with patch("guild.security.docker_sandbox.shutil.which", return_value=None):
            assert is_docker_available() is False
