"""Core agent loop — the simple while loop that drives everything.

Per Claude Code insight: keep the loop dead simple. All complexity
lives in the harness around it (storage, permissions, tools).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from guild.core.context import MicroCompact
from guild.core.models import AgentStatus, BlockDef, Message, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.ratelimit import RateLimiter, ToolQueue
from guild.core.storage import Storage
from guild.core.stuck import StuckDetector
from guild.providers.base import LLMProvider

__all__ = ["AgentLoop", "BUILTIN_TOOLS", "ToolResult", "execute_tool"]

log = logging.getLogger(__name__)

# --- Constants ---

MAX_FILE_READ_CHARS = 50_000
MAX_SHELL_OUTPUT_CHARS = 20_000
SHELL_TIMEOUT_SECONDS = 60
MAX_SEARCH_RESULTS = 200
MAX_GLOB_RESULTS = 500
DEFAULT_MAX_TURNS = 50

# Shell command denylist — blocked unless user explicitly overrides
SHELL_DENYLIST = [
    r"\brm\s+-rf\s+/",
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-f\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\b:(){ :\|:& };:",  # fork bomb
    r"\bchmod\s+-R\s+777\s+/",
    r"\bsudo\s+rm\b",
]
_DENYLIST_COMPILED = [re.compile(p) for p in SHELL_DENYLIST]


# --- ToolResult ---


@dataclass
class ToolResult:
    """Structured result from a tool execution.

    Attributes:
        success: Whether the tool executed successfully.
        output: Human-readable output (shown to the LLM).
        error: Error description if success is False.
    """

    success: bool
    output: str
    error: str | None = None

    def __str__(self) -> str:
        """Return the text representation for LLM consumption."""
        if self.success:
            return self.output
        return f"Error: {self.error}" if self.error else self.output


# --- Built-in tool definitions (JSON schema for the LLM) ---

BUILTIN_TOOLS: dict[str, dict] = {
    "file_read": {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the contents of a file. Always use this before editing a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        },
    },
    "file_write": {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": (
                "Write content to a file. Creates parent directories if needed. "
                "SAFETY: Never overwrite files without reading them first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "shell": {
        "type": "function",
        "function": {
            "name": "shell",
            "description": (
                "Execute a shell command and return stdout+stderr. "
                "SAFETY: NEVER run destructive commands (rm -rf /, git push --force, "
                "git reset --hard) unless explicitly requested. "
                "Prefer non-destructive alternatives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    "search": {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Search for a regex pattern in files under a directory. "
                "Returns matching lines with file path and line number. "
                "Use this instead of running grep in the shell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: working dir)",
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob filter, e.g. '*.py' (optional)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    "glob": {
        "type": "function",
        "function": {
            "name": "glob",
            "description": (
                "Find files matching a glob pattern. "
                "Use this instead of running find/ls in the shell."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
                    "path": {
                        "type": "string",
                        "description": "Root directory (default: working dir)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
}


# --- Tool execution ---


def _resolve_path(path_str: str, working_dir: str | None) -> Path:
    """Resolve a path, making relative paths relative to working_dir."""
    p = Path(path_str)
    if not p.is_absolute() and working_dir:
        p = Path(working_dir) / p
    return p


def _check_shell_denylist(command: str) -> str | None:
    """Check if a shell command matches the denylist.

    Returns:
        Error message if denied, None if allowed.
    """
    for pattern in _DENYLIST_COMPILED:
        if pattern.search(command):
            return f"Command blocked by security denylist: matches '{pattern.pattern}'"
    return None


async def _execute_file_read(arguments: dict, working_dir: str | None) -> ToolResult:
    """Execute file_read tool."""
    p = _resolve_path(arguments["path"], working_dir)
    if not p.exists():
        return ToolResult(success=False, output="", error=f"file not found: {p}")
    try:
        content = p.read_text(errors="replace")[:MAX_FILE_READ_CHARS]
        return ToolResult(success=True, output=content)
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _execute_file_write(arguments: dict, working_dir: str | None) -> ToolResult:
    """Execute file_write tool."""
    p = _resolve_path(arguments["path"], working_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(arguments["content"])
        return ToolResult(success=True, output=f"Wrote {len(arguments['content'])} chars to {p}")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _execute_shell(arguments: dict, working_dir: str | None) -> ToolResult:
    """Execute shell tool with denylist check."""
    command = arguments["command"]

    # Security: check denylist
    denied = _check_shell_denylist(command)
    if denied:
        return ToolResult(success=False, output="", error=denied)

    cwd = arguments.get("working_dir", working_dir)
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT_SECONDS)
        output = stdout.decode(errors="replace")[:MAX_SHELL_OUTPUT_CHARS]
        text = f"[exit {proc.returncode}]\n{output}"
        return ToolResult(
            success=proc.returncode == 0, output=text,
            error=f"exit code {proc.returncode}" if proc.returncode != 0 else None,
        )
    except asyncio.TimeoutError:
        return ToolResult(success=False, output="", error=f"command timed out after {SHELL_TIMEOUT_SECONDS}s")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))


async def _execute_search(arguments: dict, working_dir: str | None) -> ToolResult:
    """Execute search tool."""
    root = Path(arguments.get("path", working_dir or "."))
    include = arguments.get("include", "*")
    try:
        compiled = re.compile(arguments["pattern"])
    except re.error as e:
        return ToolResult(success=False, output="", error=f"invalid regex: {e}")

    results: list[str] = []
    for fp in sorted(root.rglob(include)):
        if fp.is_file() and ".git" not in fp.parts:
            try:
                for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                    if compiled.search(line):
                        results.append(f"{fp}:{i}: {line.rstrip()}")
                        if len(results) >= MAX_SEARCH_RESULTS:
                            results.append(f"... (truncated at {MAX_SEARCH_RESULTS} matches)")
                            return ToolResult(success=True, output="\n".join(results))
            except Exception:
                continue
    output = "\n".join(results) if results else "No matches found."
    return ToolResult(success=True, output=output)


async def _execute_glob(arguments: dict, working_dir: str | None) -> ToolResult:
    """Execute glob tool."""
    root = Path(arguments.get("path", working_dir or "."))
    matches = sorted(root.glob(arguments["pattern"]))
    matches = [m for m in matches if ".git" not in m.parts][:MAX_GLOB_RESULTS]
    output = "\n".join(str(m) for m in matches) if matches else "No files found."
    return ToolResult(success=True, output=output)


_TOOL_EXECUTORS = {
    "file_read": _execute_file_read,
    "file_write": _execute_file_write,
    "shell": _execute_shell,
    "search": _execute_search,
    "glob": _execute_glob,
}


async def execute_tool(name: str, arguments: dict, working_dir: str | None = None) -> ToolResult:
    """Execute a built-in tool and return a structured result."""
    executor = _TOOL_EXECUTORS.get(name)
    if executor:
        return await executor(arguments, working_dir)
    return ToolResult(success=False, output="", error=f"unknown tool '{name}'")


# --- Agent loop ---


class AgentLoop:
    """The core agent loop — call model, execute tools, repeat.

    Integrates: MicroCompact (context compression), RateLimiter (API throttling),
    ToolQueue (concurrency), StuckDetector (loop/error detection).

    Args:
        agent_id: Unique agent identifier.
        block: Block definition for this agent.
        provider: LLM provider to use.
        storage: Storage backend for persistence.
        working_dir: Working directory for tool execution.
        permission_checker: Permission enforcement.
        timeout_seconds: Max wall-clock seconds before auto-pause.
        rate_limiter: Optional rate limiter for LLM calls.
        tool_queue: Optional concurrency limiter for tool calls.
        context_window: Max tokens for context compression (0 = no compression).
    """

    def __init__(
        self,
        agent_id: str,
        block: BlockDef,
        provider: LLMProvider,
        storage: Storage,
        working_dir: str | None = None,
        permission_checker: PermissionChecker | None = None,
        timeout_seconds: int | None = None,
        rate_limiter: RateLimiter | None = None,
        tool_queue: ToolQueue | None = None,
        context_window: int = 0,
    ) -> None:
        self.agent_id = agent_id
        self.block = block
        self.provider = provider
        self.storage = storage
        self.working_dir = working_dir
        self.permission = permission_checker or PermissionChecker(block.permission)
        self.messages: list[Message] = []
        self.status = AgentStatus.IDLE
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.stuck_reason: str = ""
        self.timed_out: bool = False
        self._timeout_seconds = timeout_seconds or 0
        self._start_time: float = 0
        self._stuck_detector = StuckDetector()
        self._rate_limiter = rate_limiter
        self._tool_queue = tool_queue
        self._compactor = MicroCompact(max_tokens=context_window) if context_window > 0 else None

    async def initialize(self) -> None:
        """Set up the agent with its system prompt and register in storage."""
        system_msg = Message(role="system", content=self.block.system_prompt)
        self.messages.append(system_msg)
        await self.storage.register_agent(self.agent_id, self.block.name)
        await self.storage.append_message(self.agent_id, "system", self.block.system_prompt)

    async def run(self, user_input: str, max_turns: int = DEFAULT_MAX_TURNS) -> str:
        """Run the agent loop on a user message."""
        self.status = AgentStatus.RUNNING
        await self.storage.update_agent(self.agent_id, status="running")

        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        await self.storage.append_message(self.agent_id, "user", user_input)

        tools = self._build_tool_list()
        self._start_time = time.monotonic()

        for turn in range(max_turns):
            log.info(f"[{self.agent_id}] Turn {turn + 1}")

            # Check timeout
            if self._timeout_seconds > 0:
                elapsed = time.monotonic() - self._start_time
                if elapsed >= self._timeout_seconds:
                    self.timed_out = True
                    log.warning(f"[{self.agent_id}] Timeout after {elapsed:.0f}s")
                    self._append_and_store("assistant", f"Autonomy timeout reached ({self._timeout_seconds}s). Pausing.")
                    break

            # Check stuck
            if self._stuck_detector.is_stuck():
                self.stuck_reason = self._stuck_detector.get_reason()
                log.warning(f"[{self.agent_id}] Stuck detected: {self.stuck_reason}")
                self._append_and_store("assistant", f"I appear to be stuck: {self.stuck_reason}")
                break

            # Compress context if needed
            msgs_to_send = self.messages
            if self._compactor:
                msgs_to_send = self._compactor.compact(self.messages)

            # Rate limit LLM call
            if self._rate_limiter:
                await self._rate_limiter.acquire()

            response = await self.provider.generate(msgs_to_send, tools=tools or None)
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            await self._append_assistant_message(response)

            if not response.has_tool_call:
                break

            await self._execute_tool_calls(response.tool_calls or [])

        await self._finalize()
        return self.messages[-1].content if self.messages else ""

    def _append_and_store(self, role: str, content: str) -> None:
        """Append a message synchronously (for timeout/stuck messages)."""
        msg = Message(role=role, content=content)
        self.messages.append(msg)
        # Storage append is async but we need it in sync context — schedule it
        import asyncio
        asyncio.ensure_future(self.storage.append_message(self.agent_id, role, content))

    def _build_tool_list(self) -> list[dict]:
        """Build the tool list based on permission tier."""
        if self.permission.tier == PermissionTier.NOTHING:
            return []
        return [BUILTIN_TOOLS[t] for t in self.block.tools if t in BUILTIN_TOOLS]

    async def _append_assistant_message(self, response: "LLMResponse") -> None:
        """Append an assistant message to history and storage."""
        msg = Message(role="assistant", content=response.content, tool_calls=response.tool_calls)
        self.messages.append(msg)
        await self.storage.append_message(
            self.agent_id, "assistant", response.content, tool_calls=response.tool_calls
        )

    async def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        """Execute tool calls with permission checking, rate limiting, and stuck detection."""
        for tc in tool_calls:
            func = tc["function"]
            tool_name = func["name"]
            tool_args = (
                func["arguments"]
                if isinstance(func["arguments"], dict)
                else json.loads(func["arguments"])
            )

            allowed = self.permission.check(tool_name, self.agent_id, tool_args)
            await self.storage.log_audit(
                "permission_check", agent_id=self.agent_id,
                details=json.dumps({"tool": tool_name, "allowed": allowed, "tier": self.permission.tier.value}),
            )

            if not allowed:
                tool_result = ToolResult(success=False, output="", error=f"tool '{tool_name}' blocked by {self.permission.tier.value} tier")
                log.warning(f"[{self.agent_id}] Permission denied: {tool_result.error}")
            else:
                log.info(f"[{self.agent_id}] Tool: {tool_name}({list(tool_args.keys())})")
                await self.storage.log_audit(
                    "tool_call", agent_id=self.agent_id,
                    details=json.dumps({"tool": tool_name, "args": tool_args}),
                )
                # Execute with optional concurrency limiting
                if self._tool_queue:
                    tool_result = await self._tool_queue.execute(execute_tool(tool_name, tool_args, self.working_dir))
                else:
                    tool_result = await execute_tool(tool_name, tool_args, self.working_dir)

            # Feed stuck detector
            self._stuck_detector.record_turn(success=tool_result.success, error=tool_result.error)
            self._stuck_detector.record_tool_call({"tool": tool_name, "args": tool_args})

            # Send text to LLM
            result_text = str(tool_result)
            tool_msg = Message(role="tool", content=result_text, tool_call_id=tc.get("id"))
            self.messages.append(tool_msg)
            await self.storage.append_message(self.agent_id, "tool", result_text, tool_call_id=tc.get("id"))

    async def _finalize(self) -> None:
        """Update agent status and token counts in storage."""
        self.status = AgentStatus.DONE
        await self.storage.update_agent(
            self.agent_id, status="done",
            token_input=str(self.total_input_tokens),
            token_output=str(self.total_output_tokens),
        )
