"""Team execution engine — runs a team composition as a block graph."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from guild.blocks.registry import BlockRegistry, TeamDef
from guild.core.agent import AgentLoop
from guild.core.models import PermissionTier
from guild.core.permissions import PermissionChecker
from guild.core.storage import Storage
from guild.providers.base import LLMProvider

log = logging.getLogger(__name__)


class TeamRunner:
    """Executes a team composition by running blocks in graph order."""

    def __init__(
        self,
        team: TeamDef,
        registry: BlockRegistry,
        provider: LLMProvider,
        storage: Storage,
        working_dir: str | None = None,
        permission_tier: PermissionTier = PermissionTier.SCOPED,
    ):
        self.team = team
        self.registry = registry
        self.provider = provider
        self.storage = storage
        self.working_dir = working_dir
        self.permission_tier = permission_tier
        self.block_outputs: dict[str, dict[str, str]] = {}  # instance → {port: value}
        self.total_tokens = {"input": 0, "output": 0}

    async def run(self, initial_input: str) -> str:
        """Run the team on an initial input. Returns final output."""
        # Determine execution order via topological sort
        order = self._execution_order()
        log.info(f"Team '{self.team.name}' execution order: {order}")

        # Build loop lookup: evaluator_block → LoopDef
        loop_map = {l.evaluator_block: l for l in self.team.loops}

        for instance_name in order:
            block_type = self.team.blocks[instance_name]
            block_def = self.registry.get_block(block_type)
            if not block_def:
                log.error(f"Block type '{block_type}' not found")
                continue

            # Gather inputs for this block
            block_input = self._gather_input(instance_name, initial_input)

            # Check if this block is part of a loop (as evaluator)
            loop_def = loop_map.get(instance_name)
            iteration = 0

            while True:
                iteration += 1
                result = await self._run_block(instance_name, block_def, block_input)
                self.block_outputs[instance_name] = {"_result": result}

                # Map output to named ports
                for port in block_def.outputs:
                    self.block_outputs.setdefault(instance_name, {})[port.name] = result

                if not loop_def:
                    break

                # Check evaluator result: deterministic checks first, LLM text as fallback
                deterministic = await self._check_pass_deterministic(loop_def, self.working_dir)
                if deterministic is not None:
                    passed = deterministic
                else:
                    passed = self._check_pass_from_text(result)
                log.info(f"Loop check [{instance_name}] iteration {iteration}: pass={passed}")

                if passed or iteration >= loop_def.max_iterations:
                    if not passed:
                        log.warning(f"Loop [{instance_name}] hit max iterations ({loop_def.max_iterations})")
                    break

                # Re-run the generator block with feedback
                gen_name = loop_def.generator_block
                gen_type = self.team.blocks[gen_name]
                gen_def = self.registry.get_block(gen_type)
                if gen_def:
                    feedback_input = (
                        f"Previous attempt was rejected. Feedback:\n{result}\n\n"
                        f"Original input:\n{self._gather_input(gen_name, initial_input)}\n\n"
                        f"Please try again addressing the feedback."
                    )
                    gen_result = await self._run_block(gen_name, gen_def, feedback_input)
                    self.block_outputs[gen_name] = {"_result": gen_result}
                    for port in gen_def.outputs:
                        self.block_outputs.setdefault(gen_name, {})[port.name] = gen_result

                    # Update this evaluator's input for next iteration
                    block_input = self._gather_input(instance_name, initial_input)

        # Return the last block's output
        if order:
            last = order[-1]
            return self.block_outputs.get(last, {}).get("_result", "No output")
        return "No blocks executed"

    async def _run_block(self, instance_name: str, block_def, block_input: str) -> str:
        """Run a single block and return its output."""
        agent_id = f"{instance_name}-{uuid.uuid4().hex[:6]}"
        log.info(f"Running block '{instance_name}' ({block_def.name}) as agent {agent_id}")

        checker = PermissionChecker(
            self.permission_tier,
            allowed_paths=[self.working_dir] if self.working_dir else None,
        )
        agent = AgentLoop(
            agent_id=agent_id,
            block=block_def,
            provider=self.provider,
            storage=self.storage,
            working_dir=self.working_dir,
            permission_checker=checker,
        )
        await agent.initialize()
        result = await agent.run(block_input)
        self.total_tokens["input"] += agent.total_input_tokens
        self.total_tokens["output"] += agent.total_output_tokens
        return result

    def _gather_input(self, instance_name: str, initial_input: str) -> str:
        """Gather inputs for a block from connections or initial input."""
        parts = []

        # Check if this is the entry block
        if instance_name == self.team.entry_block:
            parts.append(initial_input)

        # Gather from connections
        for conn in self.team.connections:
            if conn.target_block == instance_name:
                src_outputs = self.block_outputs.get(conn.source_block, {})
                value = src_outputs.get(conn.source_port, src_outputs.get("_result", ""))
                if value:
                    parts.append(f"[Input from {conn.source_block}.{conn.source_port}]:\n{value}")

        return "\n\n".join(parts) if parts else initial_input

    def _execution_order(self) -> list[str]:
        """Topological sort of blocks based on connections."""
        # Build adjacency: target depends on source
        deps: dict[str, set[str]] = {name: set() for name in self.team.blocks}
        for conn in self.team.connections:
            if conn.target_block in deps and conn.source_block in self.team.blocks:
                deps[conn.target_block].add(conn.source_block)

        # Remove loop-back edges (evaluator → generator) to break cycles
        for loop in self.team.loops:
            deps.get(loop.generator_block, set()).discard(loop.evaluator_block)

        order = []
        remaining = dict(deps)
        while remaining:
            ready = [n for n, d in remaining.items() if not d]
            if not ready:
                # Cycle — just add remaining in arbitrary order
                order.extend(remaining.keys())
                break
            for n in sorted(ready):
                order.append(n)
                del remaining[n]
                for d in remaining.values():
                    d.discard(n)
        return order

    @staticmethod
    async def _check_pass_deterministic(
        loop_def: "LoopDef", working_dir: str | None
    ) -> bool | None:
        """Run deterministic verification checks.

        Args:
            loop_def: Loop definition with verification commands/files.
            working_dir: Working directory for command execution.

        Returns:
            True if all checks pass, False if any fail, None if no checks defined.
        """
        from guild.blocks.registry import LoopDef

        if not loop_def.verification_commands and not loop_def.verification_files:
            return None  # No deterministic checks — fall back to LLM parsing

        # Check files exist
        for file_path in loop_def.verification_files:
            p = Path(file_path)
            if not p.is_absolute() and working_dir:
                p = Path(working_dir) / p
            if not p.exists():
                log.info(f"Verification file missing: {p}")
                return False

        # Run verification commands
        for cmd in loop_def.verification_commands:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=working_dir,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
                if proc.returncode != 0:
                    log.info(f"Verification command failed: {cmd} (exit {proc.returncode})")
                    return False
            except Exception as e:
                log.warning(f"Verification command error: {cmd}: {e}")
                return False

        return True

    @staticmethod
    def _check_pass_from_text(result: str) -> bool:
        """Check if evaluator text output indicates pass (last resort).

        Args:
            result: Evaluator's text output.

        Returns:
            True if the output indicates pass.
        """
        lower = result.lower()
        try:
            for line in result.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    if "pass" in data:
                        return bool(data["pass"])
                    if "score" in data:
                        return data["score"] >= 70
        except (json.JSONDecodeError, KeyError):
            pass
        if "pass" in lower and "fail" not in lower:
            return True
        if "approved" in lower or "lgtm" in lower:
            return True
        return False
