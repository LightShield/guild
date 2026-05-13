"""Docker-based sandbox for isolated command execution (REQ-13.1).

Provides OS-level isolation via Docker containers:
- Project directory mounted read-write at /workspace
- Everything else isolated from the host
- Network access configurable per-agent
- Automatic fallback to direct execution when Docker unavailable
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from guild.config.constants import SHELL_TIMEOUT_SECONDS

__all__ = [
    "DOCKER_DEFAULT_IMAGE",
    "DockerSandbox",
    "is_docker_available",
    "run_in_sandbox",
]

logger = logging.getLogger(__name__)

_DOCKER_INFO_TIMEOUT: int = 10
_DOCKER_MEMORY_LIMIT = "512m"
_DOCKER_CPU_LIMIT = "1.0"

DOCKER_DEFAULT_IMAGE: str = "python:3.11-slim"
_DOCKER_TIMEOUT_BUFFER: int = 5


def is_docker_available() -> bool:
    """Check if Docker CLI exists and daemon is responsive.

    Returns True only when both the `docker` binary is on PATH and
    the daemon responds to `docker info`.
    """
    if shutil.which("docker") is None:
        logger.debug("Docker CLI not found on PATH")
        return False

    import subprocess

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=_DOCKER_INFO_TIMEOUT,
        )
        available = result.returncode == 0
        if not available:
            logger.debug("Docker daemon not responding (exit %d)", result.returncode)
        return available
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("Docker availability check failed: %s", e)
        return False


class DockerSandbox:
    """Manages Docker container lifecycle for sandboxed execution.

    Attributes:
        image: Docker image to use for containers.
        network: Whether to allow network access inside the container.
        timeout: Maximum execution time in seconds.
    """

    def __init__(
        self,
        image: str = DOCKER_DEFAULT_IMAGE,
        network: bool = False,
        timeout: float = SHELL_TIMEOUT_SECONDS,
    ) -> None:
        self.image = image
        self.network = network
        self.timeout = timeout

    async def run(
        self,
        command: str,
        working_dir: str,
    ) -> tuple[int, str, str]:
        """Run a command inside a Docker container.

        Args:
            command: Shell command to execute inside the container.
            working_dir: Host directory to mount as /workspace (read-write).

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        docker_args = self._build_docker_args(working_dir)
        docker_args.extend(["sh", "-c", command])

        logger.debug("Docker sandbox exec: %s", docker_args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return (1, "", f"Failed to start Docker: {e}")

        total_timeout = self.timeout + _DOCKER_TIMEOUT_BUFFER
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=total_timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return (1, "", f"Timeout: command exceeded {self.timeout}s limit in sandbox")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0

        return (exit_code, stdout, stderr)

    def _build_docker_args(self, working_dir: str) -> list[str]:
        """Build the docker run command arguments."""
        args = [
            "docker", "run",
            "--rm",
            "--volume", f"{working_dir}:/workspace:rw",
            "--workdir", "/workspace",
        ]

        if not self.network:
            args.append("--network=none")

        args.extend(["--memory", _DOCKER_MEMORY_LIMIT])
        args.extend(["--cpus", _DOCKER_CPU_LIMIT])

        args.append("--security-opt=no-new-privileges")

        args.append(self.image)
        return args


async def run_in_sandbox(
    command: str,
    working_dir: str,
    network: bool = False,
    timeout: float = SHELL_TIMEOUT_SECONDS,
    image: str = DOCKER_DEFAULT_IMAGE,
) -> tuple[int, str, str]:
    """Run a command inside a Docker sandbox container.

    Convenience function that creates a DockerSandbox and executes immediately.

    Args:
        command: Shell command to execute.
        working_dir: Host directory mounted read-write at /workspace.
        network: Whether to allow network access (default: False).
        timeout: Maximum execution time in seconds.
        image: Docker image to use.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    sandbox = DockerSandbox(image=image, network=network, timeout=timeout)
    return await sandbox.run(command, working_dir)
