"""Core agent loop — the simple while loop that drives everything."""

from __future__ import annotations

import json
import logging
import uuid

from guild.core.models import AgentState, AgentStatus, BlockDef, Message
from guild.core.storage import Storage
from guild.providers.base import LLMProvider, LLMResponse

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
}


async def execute_tool(name: str, arguments: dict, working_dir: str | None = None) -> str:
    """Execute a built-in tool and return the result as a string."""
    import asyncio
    import subprocess
    from pathlib import Path

    if name == "file_read":
        p = Path(arguments["path"])
        if not p.exists():
            return f"Error: file not found: {p}"
        return p.read_text(errors="replace")[:50_000]  # cap at 50k chars

    elif name == "file_write":
        p = Path(arguments["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(arguments["content"])
        return f"Wrote {len(arguments['content'])} chars to {p}"

    elif name == "shell":
        cwd = arguments.get("working_dir", working_dir)
        try:
            proc = await asyncio.create_subprocess_shell(
                arguments["command"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode(errors="replace")[:20_000]
            return f"[exit {proc.returncode}]\n{output}"
        except asyncio.TimeoutError:
            return "Error: command timed out after 60s"
        except Exception as e:
            return f"Error: {e}"

    return f"Error: unknown tool '{name}'"


class AgentLoop:
    """The core agent loop — call model, execute tools, repeat.

    Per Claude Code insight: keep this dead simple. All complexity
    lives in the harness around it (storage, permissions, tools).
    """

    def __init__(
        self,
        agent_id: str,
        block: BlockDef,
        provider: LLMProvider,
        storage: Storage,
        working_dir: str | None = None,
    ):
        self.agent_id = agent_id
        self.block = block
        self.provider = provider
        self.storage = storage
        self.working_dir = working_dir
        self.messages: list[Message] = []
        self.status = AgentStatus.IDLE
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def initialize(self) -> None:
        """Set up the agent with its system prompt."""
        system_msg = Message(role="system", content=self.block.system_prompt)
        self.messages.append(system_msg)
        await self.storage.register_agent(self.agent_id, self.block.name)
        await self.storage.append_message(self.agent_id, "system", self.block.system_prompt)

    async def run(self, user_input: str, max_turns: int = 50) -> str:
        """Run the agent loop on a user message. Returns final response."""
        self.status = AgentStatus.RUNNING
        await self.storage.update_agent(self.agent_id, status="running")

        # Add user message
        user_msg = Message(role="user", content=user_input)
        self.messages.append(user_msg)
        await self.storage.append_message(self.agent_id, "user", user_input)

        # Build tool list from block config
        tools = [BUILTIN_TOOLS[t] for t in self.block.tools if t in BUILTIN_TOOLS]

        # The loop — dead simple
        for turn in range(max_turns):
            log.info(f"[{self.agent_id}] Turn {turn + 1}")

            response = await self.provider.generate(self.messages, tools=tools or None)
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            # Append assistant message
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            self.messages.append(assistant_msg)
            await self.storage.append_message(
                self.agent_id, "assistant", response.content,
                tool_calls=response.tool_calls,
            )

            # No tool call? We're done.
            if not response.has_tool_call:
                break

            # Execute each tool call
            for tc in response.tool_calls:
                func = tc["function"]
                tool_name = func["name"]
                tool_args = func["arguments"] if isinstance(func["arguments"], dict) else json.loads(func["arguments"])

                log.info(f"[{self.agent_id}] Tool: {tool_name}({list(tool_args.keys())})")
                await self.storage.log_audit(
                    "tool_call", agent_id=self.agent_id,
                    details=json.dumps({"tool": tool_name, "args": tool_args}),
                )

                result = await execute_tool(tool_name, tool_args, self.working_dir)

                # Append tool result
                tool_msg = Message(role="tool", content=result, tool_call_id=tc.get("id"))
                self.messages.append(tool_msg)
                await self.storage.append_message(
                    self.agent_id, "tool", result, tool_call_id=tc.get("id"),
                )

        # Update final state
        self.status = AgentStatus.DONE
        await self.storage.update_agent(
            self.agent_id, status="done",
            token_input=str(self.total_input_tokens),
            token_output=str(self.total_output_tokens),
        )

        # Return the last assistant message
        return self.messages[-1].content if self.messages else ""
