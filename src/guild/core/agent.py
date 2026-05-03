"""Core agent loop — the simple while loop that drives everything."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from guild.core.models import AgentStatus, BlockDef, Message, PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMProvider

log = logging.getLogger(__name__)

# Built-in tool definitions (JSON schema for the LLM)
BUILTIN_TOOLS = {
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
                "git reset --hard) unless explicitly requested. Prefer non-destructive alternatives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "working_dir": {"type": "string", "description": "Working directory (optional)"},
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
                    "path": {"type": "string", "description": "Directory to search in (default: working dir)"},
                    "include": {"type": "string", "description": "File glob filter, e.g. '*.py' (optional)"},
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
                    "path": {"type": "string", "description": "Root directory (default: working dir)"},
                },
                "required": ["pattern"],
            },
        },
    },
}


async def execute_tool(name: str, arguments: dict, working_dir: str | None = None) -> str:
    """Execute a built-in tool and return the result as a string."""
    if name == "file_read":
        p = Path(arguments["path"])
        if not p.is_absolute() and working_dir:
            p = Path(working_dir) / p
        if not p.exists():
            return f"Error: file not found: {p}"
        return p.read_text(errors="replace")[:50_000]

    elif name == "file_write":
        p = Path(arguments["path"])
        if not p.is_absolute() and working_dir:
            p = Path(working_dir) / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(arguments["content"])
        return f"Wrote {len(arguments['content'])} chars to {p}"

    elif name == "shell":
        cwd = arguments.get("working_dir", working_dir)
        try:
            proc = await asyncio.create_subprocess_shell(
                arguments["command"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode(errors="replace")[:20_000]
            return f"[exit {proc.returncode}]\n{output}"
        except asyncio.TimeoutError:
            return "Error: command timed out after 60s"
        except Exception as e:
            return f"Error: {e}"

    elif name == "search":
        import re
        root = Path(arguments.get("path", working_dir or "."))
        pattern = arguments["pattern"]
        include = arguments.get("include", "*")
        results = []
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex: {e}"
        for fp in sorted(root.rglob(include)):
            if fp.is_file() and ".git" not in fp.parts:
                try:
                    for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                        if compiled.search(line):
                            results.append(f"{fp}:{i}: {line.rstrip()}")
                            if len(results) >= 200:
                                results.append("... (truncated at 200 matches)")
                                return "\n".join(results)
                except Exception:
                    continue
        return "\n".join(results) if results else "No matches found."

    elif name == "glob":
        root = Path(arguments.get("path", working_dir or "."))
        matches = sorted(root.glob(arguments["pattern"]))
        matches = [m for m in matches if ".git" not in m.parts][:500]
        return "\n".join(str(m) for m in matches) if matches else "No files found."

    return f"Error: unknown tool '{name}'"


class AgentLoop:
    """The core agent loop — call model, execute tools, repeat."""

    def __init__(
        self,
        agent_id: str,
        block: BlockDef,
        provider: LLMProvider,
        storage: Storage,
        working_dir: str | None = None,
        permission_checker: PermissionChecker | None = None,
    ):
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

    async def initialize(self) -> None:
        system_msg = Message(role="system", content=self.block.system_prompt)
        self.messages.append(system_msg)
        await self.storage.register_agent(self.agent_id, self.block.name)
        await self.storage.append_message(self.agent_id, "system", self.block.system_prompt)

    async def run(self, user_input: str, max_turns: int = 50) -> str:
        """Run the agent loop on a user message. Returns final response."""
        self.status = AgentStatus.RUNNING
        await self.storage.update_agent(self.agent_id, status="running")

        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        await self.storage.append_message(self.agent_id, "user", user_input)

        # Build tool list — nothing tier gets no tools
        if self.permission.tier == PermissionTier.NOTHING:
            tools = []
        else:
            tools = [BUILTIN_TOOLS[t] for t in self.block.tools if t in BUILTIN_TOOLS]

        for turn in range(max_turns):
            log.info(f"[{self.agent_id}] Turn {turn + 1}")

            response = await self.provider.generate(self.messages, tools=tools or None)
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            assistant_msg = Message(
                role="assistant", content=response.content, tool_calls=response.tool_calls,
            )
            self.messages.append(assistant_msg)
            await self.storage.append_message(
                self.agent_id, "assistant", response.content, tool_calls=response.tool_calls,
            )

            if not response.has_tool_call:
                break

            for tc in response.tool_calls:
                func = tc["function"]
                tool_name = func["name"]
                tool_args = func["arguments"] if isinstance(func["arguments"], dict) else json.loads(func["arguments"])

                # Permission check
                allowed = self.permission.check(tool_name, self.agent_id, tool_args)
                await self.storage.log_audit(
                    "permission_check", agent_id=self.agent_id,
                    details=json.dumps({"tool": tool_name, "allowed": allowed, "tier": self.permission.tier.value}),
                )

                if not allowed:
                    result = f"Permission denied: tool '{tool_name}' blocked by {self.permission.tier.value} tier."
                    log.warning(f"[{self.agent_id}] {result}")
                else:
                    log.info(f"[{self.agent_id}] Tool: {tool_name}({list(tool_args.keys())})")
                    await self.storage.log_audit(
                        "tool_call", agent_id=self.agent_id,
                        details=json.dumps({"tool": tool_name, "args": tool_args}),
                    )
                    result = await execute_tool(tool_name, tool_args, self.working_dir)

                tool_msg = Message(role="tool", content=result, tool_call_id=tc.get("id"))
                self.messages.append(tool_msg)
                await self.storage.append_message(
                    self.agent_id, "tool", result, tool_call_id=tc.get("id"),
                )

        self.status = AgentStatus.DONE
        await self.storage.update_agent(
            self.agent_id, status="done",
            token_input=str(self.total_input_tokens),
            token_output=str(self.total_output_tokens),
        )
        return self.messages[-1].content if self.messages else ""
