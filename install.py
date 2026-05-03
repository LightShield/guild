#!/usr/bin/env python3
"""Guild install script — cross-platform, single command setup.

Usage:
    python3 install.py          # Install Guild
    python3 install.py --check  # Check if dependencies are met

Creates a virtual environment, installs Guild, and sets up ~/.guild/.
Works on Linux, macOS, and Windows.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

VENV_DIR = ".venv"
GLOBAL_DIR = Path.home() / ".guild"
MIN_PYTHON = (3, 11)


def check_python() -> bool:
    """Check Python version meets minimum requirement."""
    return sys.version_info >= MIN_PYTHON


def create_venv(project_dir: Path) -> Path:
    """Create a virtual environment.

    Args:
        project_dir: Project root directory.

    Returns:
        Path to the venv's python executable.
    """
    venv_path = project_dir / VENV_DIR
    if venv_path.exists():
        print(f"  Virtual environment already exists at {venv_path}")
    else:
        print(f"  Creating virtual environment at {venv_path}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])

    if platform.system() == "Windows":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def install_package(python: Path, project_dir: Path) -> None:
    """Install Guild package in the venv.

    Args:
        python: Path to venv python.
        project_dir: Project root with pyproject.toml.
    """
    print("  Installing Guild and dependencies...")
    subprocess.check_call(
        [str(python), "-m", "pip", "install", "-e", f"{project_dir}[dev]"],
        stdout=subprocess.DEVNULL,
    )


def setup_global_dir() -> None:
    """Create ~/.guild/ with default config if it doesn't exist."""
    if GLOBAL_DIR.exists():
        print(f"  Global config directory already exists at {GLOBAL_DIR}")
        return

    print(f"  Creating global config at {GLOBAL_DIR}")
    GLOBAL_DIR.mkdir(parents=True)
    config = GLOBAL_DIR / "config.toml"
    config.write_text("""\
# Guild global configuration
# Project-level .guild/config.toml overrides these values.

[provider]
name = "ollama"
base_url = "http://localhost:11434"
model = "llama3.2"

[guild]
default_permission = "ask"
""")


def check_ollama() -> bool:
    """Check if Ollama is installed and reachable."""
    if shutil.which("ollama"):
        print("  ✓ Ollama found")
        return True
    print("  ⚠ Ollama not found. Install from https://ollama.ai")
    return False


def main() -> None:
    """Run the install process."""
    project_dir = Path(__file__).parent.resolve()

    print("Guild Installer")
    print("=" * 40)

    # Check mode
    if "--check" in sys.argv:
        ok = True
        print(f"\nPython: {sys.version}")
        if check_python():
            print(f"  ✓ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ met")
        else:
            print(f"  ✗ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")
            ok = False
        check_ollama()
        venv = project_dir / VENV_DIR
        if venv.exists():
            print(f"  ✓ Virtual environment at {venv}")
        else:
            print(f"  ⚠ No virtual environment (run install.py to create)")
        if GLOBAL_DIR.exists():
            print(f"  ✓ Global config at {GLOBAL_DIR}")
        else:
            print(f"  ⚠ No global config (run install.py to create)")
        sys.exit(0 if ok else 1)

    # Install
    print(f"\n1. Checking Python version...")
    if not check_python():
        print(f"  ✗ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, got {sys.version}")
        sys.exit(1)
    print(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}")

    print(f"\n2. Setting up virtual environment...")
    python = create_venv(project_dir)

    print(f"\n3. Installing Guild...")
    install_package(python, project_dir)

    print(f"\n4. Setting up global config...")
    setup_global_dir()

    print(f"\n5. Checking Ollama...")
    check_ollama()

    # Show activation instructions
    print(f"\n{'=' * 40}")
    print("✓ Guild installed successfully!")
    print(f"\nTo activate:")
    if platform.system() == "Windows":
        print(f"  {VENV_DIR}\\Scripts\\activate")
    else:
        print(f"  source {VENV_DIR}/bin/activate")
    print(f"\nThen run:")
    print(f"  guild init        # Initialize a project")
    print(f"  guild --help      # See all commands")


if __name__ == "__main__":
    main()
