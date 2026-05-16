"""Daemon supervisor — manages agent lifecycle, PID tracking, and signals."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Callable, Coroutine
    from pathlib import Path

from guild.config.constants import MAX_RECOVERY_CRASHES, RECOVERY_BACKOFF_BASE_SECONDS
from guild.daemon.control_socket import ControlSocket

__all__ = ["DaemonSupervisor"]

logger = logging.getLogger(__name__)


class DaemonSupervisor:
    """Minimal supervisor that runs an AgentLoop and manages its lifecycle.

    Responsibilities:
    - Creates/removes PID file in run_dir
    - Installs SIGTERM/SIGINT handlers for graceful shutdown
    - Invokes on_checkpoint callback on shutdown signal
    - Runs the agent coroutine under supervision
    - Auto-recovery: restarts crashed agents with exponential backoff
    """

    def __init__(
        self,
        run_dir: Path,
        task_id: str,
        on_checkpoint: Callable[[], Coroutine[Any, Any, None]] | None = None,
        auto_recovery: bool = False,
    ) -> None:
        self.run_dir = run_dir
        self.task_id = task_id
        self._on_checkpoint = on_checkpoint
        self._shutdown_requested = False
        self._original_sigterm: Any = None
        self._original_sigint: Any = None
        self.control_socket: ControlSocket = ControlSocket(self.socket_path)
        self._auto_recovery = auto_recovery
        self._crash_count: int = 0
        self._max_crashes: int = MAX_RECOVERY_CRASHES
        self._status: str = "running"

    @property
    def pid_path(self) -> Path:
        """Path to the PID file for this task."""
        return self.run_dir / f"{self.task_id}.pid"

    @property
    def socket_path(self) -> Path:
        """Path to the control socket for this task."""
        return self.run_dir / f"{self.task_id}.sock"

    @property
    def shutdown_requested(self) -> bool:
        """Whether a shutdown signal has been received (via signal or socket)."""
        return self._shutdown_requested or self.control_socket.shutdown_requested

    def request_shutdown(self) -> None:
        """Mark shutdown as requested (callable from signal handler)."""
        self._shutdown_requested = True

    def write_pid_file(self) -> None:
        """Write the current process PID to the PID file."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()))
        logger.debug("PID file written: %s (pid=%d)", self.pid_path, os.getpid())

    def remove_pid_file(self) -> None:
        """Remove the PID file if it exists."""
        if self.pid_path.exists():
            self.pid_path.unlink()
            logger.debug("PID file removed: %s", self.pid_path)

    async def start_control_socket(self) -> None:
        """Start the control socket server for this task."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        await self.control_socket.start()
        logger.debug("Control socket started: %s", self.socket_path)

    async def stop_control_socket(self) -> None:
        """Stop the control socket server and clean up."""
        await self.control_socket.stop()
        logger.debug("Control socket stopped: %s", self.socket_path)

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        logger.debug("Signal handlers installed for task %s", self.task_id)

    def restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
        logger.debug("Signal handlers restored for task %s", self.task_id)

    def _handle_shutdown_signal(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        """Handle SIGTERM/SIGINT by setting shutdown flag and checkpointing."""
        sig_name = signal.Signals(signum).name
        logger.debug("Received %s — requesting graceful shutdown", sig_name)
        self._shutdown_requested = True
        if self._on_checkpoint is not None:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._on_checkpoint())
            else:  # pragma: no cover — defensive
                loop.run_until_complete(self._on_checkpoint())

    @property
    def status(self) -> str:
        """Current supervisor status."""
        return self._status

    @property
    def crash_count(self) -> int:
        """Number of crashes observed during auto-recovery."""
        return self._crash_count

    async def run(
        self,
        coro: Coroutine[Any, Any, Any],
        coro_factory: Callable[[], Coroutine[Any, Any, Any]] | None = None,
    ) -> Any:
        """Run a coroutine under supervision with PID tracking and signals.

        Creates PID file, installs signal handlers, awaits the coroutine,
        and cleans up on exit (normal or exceptional).

        When auto_recovery is enabled and a coro_factory is provided, the
        supervisor will restart the agent from the factory after crashes,
        applying exponential backoff (5 * crash_count seconds). After
        _max_crashes consecutive failures, the supervisor sets status to
        'crashed_escalated' and raises the last exception.
        """
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.write_pid_file()
        self.install_signal_handlers()
        self._status = "running"
        try:
            result = await self._run_with_recovery(coro, coro_factory)
            return result
        finally:
            self.restore_signal_handlers()
            self.remove_pid_file()

    async def _run_with_recovery(
        self,
        coro: Coroutine[Any, Any, Any],
        coro_factory: Callable[[], Coroutine[Any, Any, Any]] | None = None,
    ) -> Any:
        """Internal: execute coroutine with optional auto-recovery."""
        current_coro = coro
        while True:
            try:
                result = await current_coro
                self._status = "completed"
                return result
            except Exception as exc:  # Broad catch intentional: supervisor must recover from any agent crash
                self._crash_count += 1
                logger.warning(
                    "Agent crashed (attempt %d/%d): %s",
                    self._crash_count,
                    self._max_crashes,
                    exc,
                )

                if not self._auto_recovery or coro_factory is None:
                    self._status = "crashed"
                    raise

                if self._crash_count >= self._max_crashes:
                    self._status = "crashed_escalated"
                    logger.error(
                        "Agent exceeded max crashes (%d). Escalating to human.",
                        self._max_crashes,
                    )
                    raise

                backoff = RECOVERY_BACKOFF_BASE_SECONDS * self._crash_count
                logger.debug(
                    "Auto-recovery: restarting in %d seconds (attempt %d)",
                    backoff,
                    self._crash_count,
                )
                await asyncio.sleep(backoff)
                current_coro = coro_factory()
