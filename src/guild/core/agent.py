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
from pathlib import Path

from guild.core.models import AgentStatus, BlockDef, Message, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMProvider

__all__ = ["AgentLoop", "BUILTIN_TOOLS", "execute_tool"]

log = logging.getLogger(__name__)

# --- Constants ---

MAX_FILE_READ_CHARS = 50_000
MAX_SHELL_OUTPUT_CHARS = 20_000
SHELL_TIMEOUT_SECONDS = 60
MAX_SEARCH_RESULTS = 200
MAX_GLOB_RESULTS = 500
DEFAULT_MAX_TURNS = 50

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
                "SAFETY: NEVER run destructive commands (rm -rf, git push --force, "
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
    """Resolve a path, making relative paths relative to working_dir.

    Args:
        path_str: Path string from tool arguments.
        working_dir: Working directory for relative path resolution.

    Returns:
        Resolved Path object.
    """
    p = Path(path_str)
    if not p.is_absolute() and working_dir:
        p = Path(working_dir) / p
    return p


async def _execute_file_read(arguments: dict, working_dir: str | None) -> str:
    """Execute file_read tool."""
    p = _resolve_path(arguments["path"], working_dir)
    if not p.exists():
        return f"Error: file not found: {p}"
    return p.read_text(errors="replace")[:MAX_FILE_READ_CHARS]


async def _execute_file_write(arguments: dict, working_dir: str | None) -> str:
    """Execute file_write tool."""
    p = _resolve_path(arguments["path"], working_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(arguments["content"])
    return f"Wrote {len(arguments['content'])} chars to {p}"


async def _execute_shell(arguments: dict, working_dir: str | None) -> str:
    """Execute shell tool."""
    cwd = arguments.get("working_dir", working_dir)
    try:
        proc = await asyncio.create_subprocess_shell(
            arguments["command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT_SECONDS)
        output = stdout.decode(errors="replace")[:MAX_SHELL_OUTPUT_CHARS]
        return f"[exit {proc.returncode}]\n{output}"
    except asyncio.TimeoutError:
        return f"Error: command timed out after {SHELL_TIMEOUT_SECONDS}s"
    except Exception as e:
        return f"Error: {e}"


async def _execute_search(arguments: dict, working_dir: str | None) -> str:
    """Execute search tool."""
    root = Path(arguments.get("path", working_dir or "."))
    include = arguments.get("include", "*")
    try:
        compiled = re.compile(arguments["pattern"])
    except re.error as e:
        return f"Error: invalid regex: {e}"

    results: list[str] = []
    for fp in sorted(root.rglob(include)):
        if fp.is_file() and ".git" not in fp.parts:
            try:
                for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                    if compiled.search(line):
                        results.append(f"{fp}:{i}: {line.rstrip()}")
                        if len(results) >= MAX_SEARCH_RESULTS:
                            results.append(f"... (truncated at {MAX_SEARCH_RESULTS} matches)")
                            return "\n".join(results)
            except Exception:
                continue
    return "\n".join(results) if results else "No matches found."


async def _execute_glob(arguments: dict, working_dir: str | None) -> str:
    """Execute glob tool."""
    root = Path(arguments.get("path", working_dir or "."))
    matches = sorted(root.glob(arguments["pattern"]))
    matches = [m for m in matches if ".git" not in m.parts][:MAX_GLOB_RESULTS]
    return "\n".join(str(m) for m in matches) if matches else "No files found."


_TOOL_EXECUTORS = {
    "file_read": _execute_file_read,
    "file_write": _execute_file_write,
    "shell": _execute_shell,
    "search": _execute_search,
    "glob": _execute_glob,
}


async def execute_tool(name: str, arguments: dict, working_dir: str | None = None) -> str:
    """Execute a built-in tool and return the result as a string.

    Args:
        name: Tool name.
        arguments: Tool call arguments.
        working_dir: Working directory for path resolution.

    Returns:
        Tool execution result as a string.
    """
    executor = _TOOL_EXECUTORS.get(name)
    if executor:
        return await executor(arguments, working_dir)
    return f"Error: unknown tool '{name}'"


# --- Agent loop ---


class AgentLoop:
    """The core agent loop — call model, execute tools, repeat.

    Args:
        agent_id: Unique agent identifier.
        block: Block definition for this agent.
        provider: LLM provider to use.
        storage: Storage backend for persistence.
        working_dir: Working directory for tool execution.
        permission_checker: Permission enforcement (default: from block config).
    """

    def __init__(
        self,
        agent_id: str,
        block: BlockDef,
        provider: LLMProvider,
        storage: Storage,
        working_dir: str | None = None,
        permission_checker: PermissionChecker | None = None,
        enable_stuck_detection: bool = False,
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
        self._stuck_detector: StuckDetector | None = None
        if enable_stuck_detection:
            from guild.core.stuck import StuckDetector
            self._stuck_detector = StuckDetector()

    async def initialize(self) -> None:
        """Set up the agent with its system prompt and register in storage."""
        system_msg = Message(role="system", content=self.block.system_prompt)
        self.messages.append(system_msg)
        await self.storage.register_agent(self.agent_id, self.block.name)
        await self.storage.append_message(self.agent_id, "system", self.block.system_prompt)

    async def run(self, user_input: str, max_turns: int = DEFAULT_MAX_TURNS) -> str:
        """Run the agent loop on a user message.

        Args:
            user_input: The user's message/task.
            max_turns: Maximum model calls before stopping.

        Returns:
            The agent's final response text.
        """
        self.status = AgentStatus.RUNNING
        await self.storage.update_agent(self.agent_id, status="running")

        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        await self.storage.append_message(self.agent_id, "user", user_input)

        tools = self._build_tool_list()

        for turn in range(max_turns):
            log.info(f"[{self.agent_id}] Turn {turn + 1}")

            # Check stuck detection before each turn
            if self._stuck_detector and self._stuck_detector.is_stuck():
                self.stuck_reason = self._stuck_detector.get_reason()
                log.warning(f"[{self.agent_id}] Stuck detected: {self.stuck_reason}")
                stuck_msg = Message(
                    role="assistant",
                    content=f"I appear to be stuck: {self.stuck_reason}",
                )
                self.messages.append(stuck_msg)
                await self.storage.append_message(
                    self.agent_id, "assistant", stuck_msg.content
                )
                break

            response = await self.provider.generate(self.messages, tools=tools or None)
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            await self._append_assistant_message(response)

            if not response.has_tool_call:
                break

            await self._execute_tool_calls(response.tool_calls or [])

        await self._finalize()
        return self.messages[-1].content if self.messages else ""

    def _build_tool_list(self) -> list[dict]:
        """Build the tool list based on permission tier."""
        if self.permission.tier == PermissionTier.NOTHING:
            return []
        return [BUILTIN_TOOLS[t] for t in self.block.tools if t in BUILTIN_TOOLS]

    async def _append_assistant_message(self, response: "LLMResponse") -> None:
        """Append an assistant message to history and storage."""
        from guild.providers.base import LLMResponse

        msg = Message(
            role="assistant",
            content=response.content,
            tool_calls=response.tool_calls,
        )
        self.messages.append(msg)
        await self.storage.append_message(
            self.agent_id, "assistant", response.content, tool_calls=response.tool_calls
        )

    async def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        """Execute tool calls with permission checking."""
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
                "permission_check",
                agent_id=self.agent_id,
                details=json.dumps({
                    "tool": tool_name,
                    "allowed": allowed,
                    "tier": self.permission.tier.value,
                }),
            )

            if not allowed:
                result = (
                    f"Permission denied: tool '{tool_name}' "
                    f"blocked by {self.permission.tier.value} tier."
                )
                log.warning(f"[{self.agent_id}] {result}")
            else:
                log.info(f"[{self.agent_id}] Tool: {tool_name}({list(tool_args.keys())})")
                await self.storage.log_audit(
                    "tool_call",
                    agent_id=self.agent_id,
                    details=json.dumps({"tool": tool_name, "args": tool_args}),
                )
                result = await execute_tool(tool_name, tool_args, self.working_dir)

            tool_msg = Message(role="tool", content=result, tool_call_id=tc.get("id"))
            self.messages.append(tool_msg)
            await self.storage.append_message(
                self.agent_id, "tool", result, tool_call_id=tc.get("id")
            )

            # Feed stuck detector
            if self._stuck_detector:
                is_error = result.startswith("Error:")
                self._stuck_detector.record_turn(success=not is_error, error=result if is_error else None)
                self._stuck_detector.record_tool_call({"tool": tool_name, "args": tool_args})

    async def _finalize(self) -> None:
        """Update agent status and token counts in storage."""
        self.status = AgentStatus.DONE
        await self.storage.update_agent(
            self.agent_id,
            status="done",
            token_input=str(self.total_input_tokens),
            token_output=str(self.total_output_tokens),
        )
