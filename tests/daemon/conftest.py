"""Conftest for daemon tests.

Provides a short tmp_path to avoid exceeding the 104-byte AF_UNIX socket path
limit on macOS.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path(tmp_path: Path) -> Path:  # type: ignore[override]
    """Override tmp_path with a shorter path for Unix socket compatibility."""
    short = Path(tempfile.mkdtemp(prefix="gd_"))
    yield short
    import shutil

    shutil.rmtree(short, ignore_errors=True)
