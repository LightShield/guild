"""Shell tool — execute commands with denylist and timeout (REQ-08.3, REQ-08.5, REQ-08.7)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from guild.config.constants import MAX_SHELL_OUTPUT_CHARS, SHELL_TIMEOUT_SECONDS
from guild.security.docker_sandbox import is_docker_available, run_in_sandbox
from guild.tools.base import ToolResult
from logger_python import get_logger

__all__ = [
    "MAX_SHELL_OUTPUT_CHARS",
    "SHELL_DENYLIST",
    "SHELL_TIMEOUT_SECONDS",
    "execute_shell",
]

logger = get_logger(__name__)

# Compiled regex patterns for dangerous commands.
# Each tuple: (compiled_pattern, human-readable reason).
SHELL_DENYLIST: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+.*-[^\s]*r[^\s]*f[^\s]*\s+/"), "rm -rf / is blocked"),
    (re.compile(r"\brm\s+.*-[^\s]*f[^\s]*r[^\s]*\s+/"), "rm -rf / is blocked"),
    (re.compile(r"\bsudo\s+rm\b"), "sudo rm is blocked"),
    (re.compile(r"\bgit\s+push\s+.*--force"), "git push --force is blocked"),
    (re.compile(r"\bgit\s+push\s+-f\b"), "git push -f is blocked"),
    (re.compile(r"\bgit\s+reset\s+--hard"), "git reset --hard is blocked"),
    (re.compile(r":\(\)\s*\{.*\|.*&\s*\}\s*;"), "fork bomb is blocked"),
    (re.compile(r"\bmkfs\b"), "mkfs is blocked"),
    (re.compile(r"\bdd\s+.*of=/dev/"), "dd to device is blocked"),
    (re.compile(r">\s*/dev/sd[a-z]"), "overwrite device is blocked"),
    (re.compile(r"\bchmod\s+.*777\s+/"), "chmod 777 / is blocked"),
    (re.compile(r"\bcurl\b.*\|\s*\bbash\b"), "curl | bash is blocked"),
    (re.compile(r"\bwget\b.*\|\s*\bbash\b"), "wget | bash is blocked"),
]


def _check_denylist(command: str) -> str | None:
    """Return denial reason if command matches denylist, else None."""
    for pattern, reason in SHELL_DENYLIST:
        if pattern.search(command):
            return reason
    return None


async def execute_shell(
    args: dict[str, Any],
    working_dir: str | None = None,
    sandbox_mode: str = "auto",
    sandbox_network: bool = False,
) -> ToolResult:
    """Execute a shell command with denylist check and timeout.

    Args:
        args: Must contain "command". Optional "timeout" (seconds).
        working_dir: Directory in which to execute the command.
        sandbox_mode: "auto" (docker if available), "docker" (require), "none" (disable).
        sandbox_network: Whether sandboxed commands get network access.

    Returns:
        ToolResult with stdout/stderr on success, error on failure.
    """
    command = args.get("command", "")
    if not command:
        return ToolResult(success=False, output="", error="Missing required argument: command")

    denial = _check_denylist(command)
    if denial:
        logger.info("Shell command denied: %s (reason: %s)", command, denial)
        return ToolResult(success=False, output="", error=f"Command blocked: {denial}")

    timeout = args.get("timeout", SHELL_TIMEOUT_SECONDS)
    if not isinstance(timeout, (int, float)):
        timeout = SHELL_TIMEOUT_SECONDS

    use_sandbox = _should_use_sandbox(sandbox_mode)
    if use_sandbox and working_dir:
        return await _run_sandboxed(command, working_dir, timeout, sandbox_network)

    return await _run_command(command, working_dir, timeout)


def _should_use_sandbox(sandbox_mode: str) -> bool:
    """Determine whether to use Docker sandbox based on mode and availability."""
    if sandbox_mode == "none":
        return False
    if sandbox_mode == "docker":
        return True
    # "auto" mode: use Docker if available
    return is_docker_available()


async def _run_sandboxed(
    command: str,
    working_dir: str,
    timeout: float,
    network: bool,
) -> ToolResult:
    """Run command inside Docker sandbox and format result."""
    exit_code, stdout, stderr = await run_in_sandbox(
        command=command,
        working_dir=working_dir,
        network=network,
        timeout=timeout,
    )
    # Detect timeout from sandbox stderr message
    if exit_code != 0 and "timeout" in stderr.lower():
        return ToolResult(
            success=False,
            output="",
            error=f"Timeout: command exceeded {timeout}s limit",
        )
    return _format_result(stdout, stderr, exit_code)


async def _run_command(command: str, working_dir: str | None, timeout: float) -> ToolResult:
    """Run command as subprocess with timeout and output limits."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )
    except OSError as e:
        return ToolResult(success=False, output="", error=f"Failed to start: {e}")

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(
            success=False,
            output="",
            error=f"Timeout: command exceeded {timeout}s limit",
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    return _format_result(stdout, stderr, proc.returncode or 0)


def _format_result(stdout: str, stderr: str, exit_code: int) -> ToolResult:
    """Format command output into a ToolResult."""
    parts: list[str] = []
    if stdout:
        parts.append(stdout.rstrip())
    if stderr:
        parts.append(f"[stderr]\n{stderr.rstrip()}")
    parts.append(f"[Exit code: {exit_code}]")

    output = "\n".join(parts)

    if len(output) > MAX_SHELL_OUTPUT_CHARS:
        output = output[:MAX_SHELL_OUTPUT_CHARS] + "\n\n[Truncated — output exceeds limit]"

    if exit_code != 0:
        return ToolResult(
            success=False,
            output=output,
            error=f"Command exited with code {exit_code}",
        )

    return ToolResult(success=True, output=output)
