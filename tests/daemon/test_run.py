"""Tests for daemon/run.py — daemon runner entry point (REQ-23.6)."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
@pytest.mark.req("REQ-23.6")
class TestDaemonRunMain:
    """main() validates arguments before running."""

    def test_exits_with_error_when_no_args(self) -> None:
        """main() exits with code 1 when called without arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "guild.daemon.run"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_exits_with_error_when_one_arg(self) -> None:
        """main() exits with code 1 when called with only task_id."""
        result = subprocess.run(
            [sys.executable, "-m", "guild.daemon.run", "fake-task-id"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
