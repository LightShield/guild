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
    # Provider defaults
    "DEFAULT_MAX_TOKENS",
    # Context management
    "DEFAULT_CONTEXT_MAX_TOKENS",
    "DEFAULT_COMPACT_THRESHOLD",
    "DEFAULT_PRESERVE_RECENT",
    "CHARS_PER_TOKEN",
    "TRUNCATION_MARKER",
    "MIN_CONTENT_LEN",
    "ACTION_SUMMARY_MAX_CHARS",
    # API
    "WEBSOCKET_POLL_SECONDS",
    # Learning
    "MIN_INJECTION_CONFIDENCE",
    "LEARNING_CONTENT_MAX_CHARS",
    "DEFAULT_CONFIDENCE",
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
    # File operations
    "MAX_FILE_READ_CHARS",
    # Search
    "MAX_SEARCH_RESULTS",
    "MAX_GLOB_RESULTS",
    # Plugin cache
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_CACHE_MAX_SIZE",
    # Docker sandbox
    "DOCKER_INFO_TIMEOUT",
    "DOCKER_MEMORY_LIMIT",
    "DOCKER_CPU_LIMIT",
    "DOCKER_DEFAULT_IMAGE",
    "DOCKER_TIMEOUT_BUFFER",
    # Completion heuristics
    "SIMPLE_ACTION_THRESHOLD",
    # Budget
    "BUDGET_ALERT_THRESHOLDS",
    # Daemon supervisor
    "MAX_RECOVERY_CRASHES",
    "RECOVERY_BACKOFF_BASE_SECONDS",
    # Daemon resource
    "DEFAULT_CPU_THRESHOLD",
    "DEFAULT_POLITE_DELAY_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_VRAM_PRESSURE_PERCENT",
    # Provider
    "OLLAMA_CLIENT_TIMEOUT_SECONDS",
    "PROVIDER_CHAIN_MAX_DEPTH",
    # Block execution
    "BLOCK_RETRY_MAX",
    "BLOCK_RETRY_DELAY_SECONDS",
    "TASK_DESC_PREVIEW_CHARS",
    "TASK_RESULT_PREVIEW_CHARS",
    "LOOP_ESCALATION_THRESHOLD",
    # Knowledge/memory
    "STALE_DAYS",
    "MAX_INDEX_LINES",
    # Orchestration
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_LOOP_MAX_ITERATIONS",
    "HEURISTIC_PASS_SCORE",
    "HEURISTIC_FAIL_SCORE",
    "SUB_AGENT_MAX_TURNS",
    # CLI task runner
    "SECONDS_PER_TURN_ESTIMATE",
    "MIN_TURNS",
    "MAX_TURNS_CAP",
    "AGENT_ID_PREFIX_LEN",
    # Temporal knowledge
    "DEFAULT_DECISION_HISTORY_LIMIT",
    "DEFAULT_CONTEXT_DECISIONS",
    "BRIEF_DECISION_LIMIT",
    "TEMPORAL_CMD_TIMEOUT_SECONDS",
    # Spawner
    "MAX_SPAWN_DEPTH",
    "TASK_LOG_PREVIEW_CHARS",
    # RPG UI
    "PROGRESS_BAR_WIDTH",
    # Agent loop content preview
    "LOOP_CONTENT_PREVIEW_CHARS",
    # Observability
    "REPLAY_CONTENT_MAX_CHARS",
    # Eval framework
    "DURATION_REGRESSION_FACTOR",
    "TOKEN_REGRESSION_FACTOR",
    "TOOL_CALL_REGRESSION_FACTOR",
    "EVAL_MAX_TURNS",
    # Git worktree
    "BRANCH_PREFIX",
    "STAGING_BRANCH_SUFFIX",
    "STAGING_DIR_NAME",
    # Escalation
    "NOTIFICATION_TITLE",
    # JSON-RPC error codes
    "JSONRPC_PARSE_ERROR",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INTERNAL_ERROR",
    # HTTP status codes
    "HTTP_BAD_REQUEST",
    "HTTP_NOT_FOUND",
    # CLI column widths
    "CLI_ID_COL_WIDTH",
    "CLI_CONTEXT_COL_WIDTH",
    "CLI_RESULT_COL_WIDTH",
    "CLI_DESC_COL_WIDTH",
    # Daemon platform
    "PLATFORM_SUBPROCESS_TIMEOUT",
    "DEFAULT_IDLE_THRESHOLD_SECONDS",
    # Storage query defaults
    "DEFAULT_QUERY_LIMIT",
    "PRUNING_RETENTION_DAYS",
    # API server
    # Memory list defaults
    "DEFAULT_MEMORY_LIST_LIMIT",
    # Logging
    "LOG_PREVIEW_MAX_CHARS",
    # Rate limiting
    "DEFAULT_RATE_LIMIT_CALLS",
    "DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
    "DEFAULT_API_PORT",
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
# Provider defaults
# ---------------------------------------------------------------------------
DEFAULT_MAX_TOKENS: int = 4096

# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------
DEFAULT_CONTEXT_MAX_TOKENS: int = 8000
DEFAULT_COMPACT_THRESHOLD: float = 0.7
DEFAULT_PRESERVE_RECENT: int = 4
CHARS_PER_TOKEN: int = 4
TRUNCATION_MARKER: str = "\n...[truncated]..."
MIN_CONTENT_LEN: int = 50
ACTION_SUMMARY_MAX_CHARS: int = 100

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
WEBSOCKET_POLL_SECONDS: int = 2

# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
MIN_INJECTION_CONFIDENCE: float = 0.5
LEARNING_CONTENT_MAX_CHARS: int = 500
DEFAULT_CONFIDENCE: float = 0.3

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

# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
MAX_FILE_READ_CHARS: int = 50_000

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
MAX_SEARCH_RESULTS: int = 200
MAX_GLOB_RESULTS: int = 500

# ---------------------------------------------------------------------------
# Plugin cache
# ---------------------------------------------------------------------------
DEFAULT_CACHE_TTL_SECONDS: int = 300
DEFAULT_CACHE_MAX_SIZE: int = 100

# ---------------------------------------------------------------------------
# Docker sandbox
# ---------------------------------------------------------------------------
DOCKER_INFO_TIMEOUT: int = 10
DOCKER_MEMORY_LIMIT: str = "512m"
DOCKER_CPU_LIMIT: str = "1.0"
DOCKER_DEFAULT_IMAGE: str = "python:3.11-slim"
DOCKER_TIMEOUT_BUFFER: int = 5

# ---------------------------------------------------------------------------
# Completion heuristics
# ---------------------------------------------------------------------------
SIMPLE_ACTION_THRESHOLD: int = 2

# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
BUDGET_ALERT_THRESHOLDS: list[float] = [0.8, 0.9, 1.0]

# ---------------------------------------------------------------------------
# Daemon supervisor
# ---------------------------------------------------------------------------
MAX_RECOVERY_CRASHES: int = 3
RECOVERY_BACKOFF_BASE_SECONDS: int = 5

# ---------------------------------------------------------------------------
# Daemon resource
# ---------------------------------------------------------------------------
DEFAULT_CPU_THRESHOLD: float = 80.0
DEFAULT_POLITE_DELAY_SECONDS: float = 10.0
DEFAULT_POLL_INTERVAL_SECONDS: float = 5.0
DEFAULT_VRAM_PRESSURE_PERCENT: float = 85.0

# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------
OLLAMA_CLIENT_TIMEOUT_SECONDS: float = 120.0
PROVIDER_CHAIN_MAX_DEPTH: int = 10

# ---------------------------------------------------------------------------
# Block execution (team runner)
# ---------------------------------------------------------------------------
BLOCK_RETRY_MAX: int = 5
BLOCK_RETRY_DELAY_SECONDS: float = 5.0
TASK_DESC_PREVIEW_CHARS: int = 100
TASK_RESULT_PREVIEW_CHARS: int = 500
LOOP_ESCALATION_THRESHOLD: int = 2

# ---------------------------------------------------------------------------
# Knowledge/memory
# ---------------------------------------------------------------------------
STALE_DAYS: int = 30
MAX_INDEX_LINES: int = 200

# ---------------------------------------------------------------------------
# Temporal knowledge
# ---------------------------------------------------------------------------
DEFAULT_DECISION_HISTORY_LIMIT: int = 20
DEFAULT_CONTEXT_DECISIONS: int = 10
BRIEF_DECISION_LIMIT: int = 5
TEMPORAL_CMD_TIMEOUT_SECONDS: int = 10

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
DEFAULT_MAX_RETRIES: int = 1
DEFAULT_LOOP_MAX_ITERATIONS: int = 5
HEURISTIC_PASS_SCORE: int = 80
HEURISTIC_FAIL_SCORE: int = 30
SUB_AGENT_MAX_TURNS: int = 30

# ---------------------------------------------------------------------------
# Spawner
# ---------------------------------------------------------------------------
MAX_SPAWN_DEPTH: int = 5
TASK_LOG_PREVIEW_CHARS: int = 80

# ---------------------------------------------------------------------------
# CLI task runner
# ---------------------------------------------------------------------------
SECONDS_PER_TURN_ESTIMATE: int = 10
MIN_TURNS: int = 5
MAX_TURNS_CAP: int = 200
AGENT_ID_PREFIX_LEN: int = 8

# ---------------------------------------------------------------------------
# RPG UI
# ---------------------------------------------------------------------------
PROGRESS_BAR_WIDTH: int = 10

# ---------------------------------------------------------------------------
# Agent loop content preview
# ---------------------------------------------------------------------------
LOOP_CONTENT_PREVIEW_CHARS: int = 200

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
REPLAY_CONTENT_MAX_CHARS: int = 500

# ---------------------------------------------------------------------------
# Eval framework
# ---------------------------------------------------------------------------
DURATION_REGRESSION_FACTOR: float = 2.0
TOKEN_REGRESSION_FACTOR: float = 2.0
TOOL_CALL_REGRESSION_FACTOR: float = 2.0
EVAL_MAX_TURNS: int = 20

# ---------------------------------------------------------------------------
# Git worktree
# ---------------------------------------------------------------------------
BRANCH_PREFIX: str = "guild/"
STAGING_BRANCH_SUFFIX: str = "staging"
STAGING_DIR_NAME: str = "_staging"

# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------
NOTIFICATION_TITLE: str = "Guild"

# ---------------------------------------------------------------------------
# JSON-RPC error codes (standard + application-specific)
# ---------------------------------------------------------------------------
JSONRPC_PARSE_ERROR: int = -32700
JSONRPC_INVALID_REQUEST: int = -32600
JSONRPC_METHOD_NOT_FOUND: int = -32601
JSONRPC_INVALID_PARAMS: int = -32602
JSONRPC_INTERNAL_ERROR: int = -32001

# ---------------------------------------------------------------------------
# HTTP status codes
# ---------------------------------------------------------------------------
HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

# ---------------------------------------------------------------------------
# CLI column widths
# ---------------------------------------------------------------------------
CLI_ID_COL_WIDTH: int = 12
CLI_CONTEXT_COL_WIDTH: int = 40
CLI_RESULT_COL_WIDTH: int = 40
CLI_DESC_COL_WIDTH: int = 50

# ---------------------------------------------------------------------------
# Daemon platform
# ---------------------------------------------------------------------------
PLATFORM_SUBPROCESS_TIMEOUT: int = 5
DEFAULT_IDLE_THRESHOLD_SECONDS: float = 300.0

# ---------------------------------------------------------------------------
# Storage query defaults
# ---------------------------------------------------------------------------
DEFAULT_QUERY_LIMIT: int = 50
PRUNING_RETENTION_DAYS: int = 30

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
DEFAULT_API_PORT: int = 8585

# ---------------------------------------------------------------------------
# Memory list defaults
# ---------------------------------------------------------------------------
DEFAULT_MEMORY_LIST_LIMIT: int = 200

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_PREVIEW_MAX_CHARS: int = 80

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
DEFAULT_RATE_LIMIT_CALLS: int = 30
DEFAULT_RATE_LIMIT_WINDOW_SECONDS: float = 60.0
