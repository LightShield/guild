"""Centralized operational constants for the Guild project.

Single source of truth for magic numbers and identity strings used across
multiple modules. Import from here rather than defining locally.
"""

__all__ = [
    # Shell execution
    "SHELL_TIMEOUT_SECONDS",
    "MAX_SHELL_OUTPUT_CHARS",
    # CLI provider
    "CLI_PROVIDER_TIMEOUT_SECONDS",
    # Agent loop
    "DEFAULT_MAX_TURNS",
    # Context management
    "DEFAULT_CONTEXT_MAX_TOKENS",
    "DEFAULT_COMPACT_THRESHOLD",
    "DEFAULT_PRESERVE_RECENT",
    # API
    "WEBSOCKET_POLL_SECONDS",
    # Learning
    "MIN_INJECTION_CONFIDENCE",
    "LEARNING_CONTENT_MAX_CHARS",
    # Memory/confidence
    "CONFIDENCE_VALIDATE_INCREMENT",
    "CONFIDENCE_INVALIDATE_DECREMENT",
    "CONFIDENCE_DECAY_DECREMENT",
    "MEMORY_SUMMARY_MAX_CHARS",
    # Directory/file names
    "GUILD_DIR_NAME",
    "CONFIG_FILENAME",
    "DB_FILENAME",
    "AGENTS_FILENAME",
    "PERMISSIONS_FILENAME",
    "SECURITY_FILENAME",
]

# ---------------------------------------------------------------------------
# Shell execution
# ---------------------------------------------------------------------------
SHELL_TIMEOUT_SECONDS: int = 60
MAX_SHELL_OUTPUT_CHARS: int = 20_000

# ---------------------------------------------------------------------------
# CLI provider
# ---------------------------------------------------------------------------
CLI_PROVIDER_TIMEOUT_SECONDS: int = 120

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
DEFAULT_MAX_TURNS: int = 50

# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------
DEFAULT_CONTEXT_MAX_TOKENS: int = 8000
DEFAULT_COMPACT_THRESHOLD: float = 0.7
DEFAULT_PRESERVE_RECENT: int = 4

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
WEBSOCKET_POLL_SECONDS: int = 2

# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
MIN_INJECTION_CONFIDENCE: float = 0.5
LEARNING_CONTENT_MAX_CHARS: int = 500

# ---------------------------------------------------------------------------
# Memory/confidence
# ---------------------------------------------------------------------------
CONFIDENCE_VALIDATE_INCREMENT: float = 0.1
CONFIDENCE_INVALIDATE_DECREMENT: float = 0.15
CONFIDENCE_DECAY_DECREMENT: float = 0.05
MEMORY_SUMMARY_MAX_CHARS: int = 200

# ---------------------------------------------------------------------------
# Directory/file names
# ---------------------------------------------------------------------------
GUILD_DIR_NAME: str = ".guild"
CONFIG_FILENAME: str = "config.toml"
DB_FILENAME: str = "guild.db"
AGENTS_FILENAME: str = "agents.toml"
PERMISSIONS_FILENAME: str = "permissions.toml"
SECURITY_FILENAME: str = "security.toml"
