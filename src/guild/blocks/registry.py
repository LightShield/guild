"""Block system — definitions, loading, registry, and team composition."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from guild.core.models import BlockDef, PermissionTier, PortDef


# --- Built-in atomic blocks ---

BUILTIN_BLOCKS: dict[str, BlockDef] = {
    "planner": BlockDef(
        name="planner",
        role="planner",
        system_prompt=(
            "You are a planner. Given a high-level task, decompose it into a structured plan "
            "with clear subtasks and acceptance criteria. Output a numbered list of subtasks, "
            "each with a description and done-criteria."
        ),
        tools=["file_read", "search", "glob"],
        inputs=[PortDef(name="task", type_tag="text")],
        outputs=[PortDef(name="plan", type_tag="plan")],
    ),
    "coder": BlockDef(
        name="coder",
        role="coder",
        system_prompt=(
            "You are a coder. Write code to fulfill the given specification. "
            "Always read existing files before modifying them. Write clean, minimal code. "
            "SAFETY: Never overwrite files without reading them first."
        ),
        tools=["file_read", "file_write", "shell", "search", "glob"],
        inputs=[PortDef(name="spec", type_tag="plan"), PortDef(name="context", type_tag="files")],
        outputs=[PortDef(name="changes", type_tag="code-changes")],
    ),
    "reviewer": BlockDef(
        name="reviewer",
        role="reviewer",
        system_prompt=(
            "You are a code reviewer. Review the given code changes for correctness, style, "
            "and spec compliance. Be skeptical — look for bugs, edge cases, and missing tests. "
            "Output: pass/fail, score 0-100, and detailed feedback."
        ),
        tools=["file_read", "search", "glob"],
        inputs=[PortDef(name="changes", type_tag="code-changes"), PortDef(name="spec", type_tag="plan")],
        outputs=[PortDef(name="result", type_tag="review")],
    ),
    "tester": BlockDef(
        name="tester",
        role="tester",
        system_prompt=(
            "You are a tester. Write and run tests for the given code. "
            "Focus on correctness, edge cases, and spec coverage. "
            "Output: pass/fail, test results, and coverage summary."
        ),
        tools=["file_read", "file_write", "shell", "search", "glob"],
        inputs=[PortDef(name="changes", type_tag="code-changes"), PortDef(name="spec", type_tag="plan")],
        outputs=[PortDef(name="result", type_tag="test-results")],
    ),
    "evaluator": BlockDef(
        name="evaluator",
        role="evaluator",
        system_prompt=(
            "You are a skeptical evaluator. Judge the quality of the given artifact against "
            "the provided criteria. Be critical — do not praise mediocre work. "
            "Output JSON: {\"pass\": bool, \"score\": 0-100, \"feedback\": \"...\", \"details\": {}}"
        ),
        tools=["file_read", "search", "glob"],
        inputs=[PortDef(name="artifact", type_tag="any"), PortDef(name="criteria", type_tag="text")],
        outputs=[PortDef(name="result", type_tag="review")],
    ),
    "researcher": BlockDef(
        name="researcher",
        role="researcher",
        system_prompt=(
            "You are a researcher. Investigate the given question by reading files, "
            "searching code, and gathering context. Produce a clear findings report."
        ),
        tools=["file_read", "search", "glob", "shell"],
        inputs=[PortDef(name="question", type_tag="text")],
        outputs=[PortDef(name="report", type_tag="text")],
    ),
    "writer": BlockDef(
        name="writer",
        role="writer",
        system_prompt=(
            "You are a technical writer. Produce clear, well-structured documentation "
            "or reports based on the given topic and context."
        ),
        tools=["file_read", "file_write", "search"],
        inputs=[PortDef(name="topic", type_tag="text"), PortDef(name="context", type_tag="any")],
        outputs=[PortDef(name="doc", type_tag="document")],
    ),
    "learner": BlockDef(
        name="learner",
        role="learner",
        system_prompt=(
            "You are a learning extractor. Review the session logs and outcomes of a completed task. "
            "Extract: patterns (what worked), anti-patterns (what failed), tool tips, and domain knowledge. "
            "Output structured JSON with category, content, and confidence (0.0-1.0) for each learning."
        ),
        tools=["file_read", "search"],
        inputs=[PortDef(name="logs", type_tag="any"), PortDef(name="outcomes", type_tag="any")],
        outputs=[PortDef(name="insights", type_tag="learnings")],
    ),
}


# --- Team composition ---


class Connection(BaseModel):
    """A connection between two blocks in a team graph."""
    source_block: str
    source_port: str
    target_block: str
    target_port: str


class LoopDef(BaseModel):
    """A feedback loop in the team graph."""
    evaluator_block: str  # block whose output determines loop continuation
    generator_block: str  # block to re-run on failure
    max_iterations: int = 5


class TeamDef(BaseModel):
    """A team composition — a graph of connected blocks."""
    name: str
    description: str = ""
    blocks: dict[str, str] = Field(default_factory=dict)  # instance_name → block_type
    connections: list[Connection] = Field(default_factory=list)
    loops: list[LoopDef] = Field(default_factory=list)
    entry_block: str = ""  # which block receives the initial input


# --- Built-in teams ---

BUILTIN_TEAMS: dict[str, TeamDef] = {
    "dev-loop": TeamDef(
        name="dev-loop",
        description="Standard development cycle: plan → code → test → review",
        blocks={"planner": "planner", "coder": "coder", "tester": "tester", "reviewer": "reviewer"},
        connections=[
            Connection(source_block="planner", source_port="plan", target_block="coder", target_port="spec"),
            Connection(source_block="coder", source_port="changes", target_block="tester", target_port="changes"),
            Connection(source_block="planner", source_port="plan", target_block="tester", target_port="spec"),
            Connection(source_block="coder", source_port="changes", target_block="reviewer", target_port="changes"),
            Connection(source_block="planner", source_port="plan", target_block="reviewer", target_port="spec"),
        ],
        loops=[LoopDef(evaluator_block="reviewer", generator_block="coder", max_iterations=3)],
        entry_block="planner",
    ),
    "verified-coder": TeamDef(
        name="verified-coder",
        description="Code with built-in quality gate: coder → evaluator loop",
        blocks={"coder": "coder", "evaluator": "evaluator"},
        connections=[
            Connection(source_block="coder", source_port="changes", target_block="evaluator", target_port="artifact"),
        ],
        loops=[LoopDef(evaluator_block="evaluator", generator_block="coder", max_iterations=5)],
        entry_block="coder",
    ),
    "research-and-implement": TeamDef(
        name="research-and-implement",
        description="Investigate first, then build: researcher → planner → coder",
        blocks={"researcher": "researcher", "planner": "planner", "coder": "coder"},
        connections=[
            Connection(source_block="researcher", source_port="report", target_block="planner", target_port="task"),
            Connection(source_block="planner", source_port="plan", target_block="coder", target_port="spec"),
        ],
        entry_block="researcher",
    ),
}


# --- Block registry ---


class BlockRegistry:
    """Registry of available blocks and teams."""

    def __init__(self) -> None:
        self.blocks: dict[str, BlockDef] = dict(BUILTIN_BLOCKS)
        self.teams: dict[str, TeamDef] = dict(BUILTIN_TEAMS)

    def load_from_dir(self, blocks_dir: Path) -> None:
        """Load custom block definitions from TOML files in a directory."""
        if not blocks_dir.is_dir():
            return
        for f in blocks_dir.glob("*.toml"):
            try:
                with open(f, "rb") as fh:
                    raw = tomllib.load(fh)
                if "block" in raw:
                    b = raw["block"]
                    inputs = [PortDef(**p) for p in b.get("inputs", [])]
                    outputs = [PortDef(**p) for p in b.get("outputs", [])]
                    block = BlockDef(
                        name=b["name"],
                        role=b.get("role", b["name"]),
                        system_prompt=b.get("system_prompt", ""),
                        model=b.get("model"),
                        tools=b.get("tools", []),
                        inputs=inputs,
                        outputs=outputs,
                        permission=PermissionTier(b.get("permission", "ask")),
                        max_retries=b.get("max_retries", 1),
                    )
                    self.blocks[block.name] = block
                if "team" in raw:
                    t = raw["team"]
                    conns = [Connection(**c) for c in t.get("connections", [])]
                    loops = [LoopDef(**l) for l in t.get("loops", [])]
                    team = TeamDef(
                        name=t["name"],
                        description=t.get("description", ""),
                        blocks=t.get("blocks", {}),
                        connections=conns,
                        loops=loops,
                        entry_block=t.get("entry_block", ""),
                    )
                    self.teams[team.name] = team
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to load block from {f}: {e}")

    def get_block(self, name: str) -> BlockDef | None:
        return self.blocks.get(name)

    def get_team(self, name: str) -> TeamDef | None:
        return self.teams.get(name)

    def validate_team(self, team: TeamDef) -> list[str]:
        """Validate a team composition. Returns list of errors (empty = valid)."""
        errors = []
        for instance, block_type in team.blocks.items():
            if block_type not in self.blocks:
                errors.append(f"Block type '{block_type}' (instance '{instance}') not found in registry")

        for conn in team.connections:
            if conn.source_block not in team.blocks:
                errors.append(f"Connection source '{conn.source_block}' not in team blocks")
            if conn.target_block not in team.blocks:
                errors.append(f"Connection target '{conn.target_block}' not in team blocks")

            # Port type compatibility check
            src_type = team.blocks.get(conn.source_block)
            tgt_type = team.blocks.get(conn.target_block)
            if src_type and tgt_type:
                src_block = self.blocks.get(src_type)
                tgt_block = self.blocks.get(tgt_type)
                if src_block and tgt_block:
                    src_port = next((p for p in src_block.outputs if p.name == conn.source_port), None)
                    tgt_port = next((p for p in tgt_block.inputs if p.name == conn.target_port), None)
                    if src_port and tgt_port:
                        if src_port.type_tag != "any" and tgt_port.type_tag != "any":
                            if src_port.type_tag != tgt_port.type_tag:
                                errors.append(
                                    f"Port type mismatch: {conn.source_block}.{conn.source_port} "
                                    f"({src_port.type_tag}) → {conn.target_block}.{conn.target_port} "
                                    f"({tgt_port.type_tag})"
                                )

        if team.entry_block and team.entry_block not in team.blocks:
            errors.append(f"Entry block '{team.entry_block}' not in team blocks")

        return errors
