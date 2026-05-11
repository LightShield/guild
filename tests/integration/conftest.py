"""Integration test configuration."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path() -> Path:  # type: ignore[override]
    """Short temp path to avoid Unix socket path length limits."""
    short = Path(tempfile.mkdtemp(prefix="gi_"))
    yield short
    shutil.rmtree(short, ignore_errors=True)
