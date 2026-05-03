"""Tests for install script (REQ-02.2)."""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


class TestInstallScript:
    """REQ-02.2: Single install script, cross-platform."""

    def test_check_mode_runs(self):
        """install.py --check should run without error."""
        result = subprocess.run(
            [sys.executable, "install.py", "--check"],
            capture_output=True, text=True, cwd=".",
        )
        assert "Python" in result.stdout

    def test_script_is_valid_python(self):
        """install.py should be valid Python syntax."""
        result = subprocess.run(
            [sys.executable, "-c", "import py_compile; py_compile.compile('install.py', doraise=True)"],
            capture_output=True, text=True, cwd=".",
        )
        assert result.returncode == 0
