"""E2E test configuration — shared fixtures for acceptance tests."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_path() -> Path:  # type: ignore[override]
    """Short temp path to avoid Unix socket path length limits on macOS."""
    short = Path(tempfile.mkdtemp(prefix="ge_"))
    yield short  # type: ignore[misc]
    shutil.rmtree(short, ignore_errors=True)
