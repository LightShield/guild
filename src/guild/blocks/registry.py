"""Block registry — catalog of available blocks and teams."""

import logging
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from guild.permissions.checker import PermissionTier

from .definition import BlockDef, Connection, LoopDef, PortDef, TeamDef
from .port_types import check_port_compatibility

__all__ = ["BlockRegistry"]

logger = logging.getLogger(__name__)


class BlockRegistry:
    """Catalog of available blocks (built-in + user-defined)."""

    def __init__(self) -> None:
        self._blocks: dict[str, BlockDef] = {}
        self._teams: dict[str, TeamDef] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Register built-in blocks (planner, coder, reviewer, etc.)."""
        for block in self._builtin_block_definitions():
            self._blocks[block.name] = block

    def _builtin_block_definitions(self) -> list[BlockDef]:
        """Return the list of built-in block definitions."""
        return [
            self._planner_block(),
            self._coder_block(),
            self._reviewer_block(),
            self._tester_block(),
            self._evaluator_block(),
            self._researcher_block(),
        ]

    def _planner_block(self) -> BlockDef:
        """Define the planner block."""
        return BlockDef(
            name="planner",
            role="planner",
            system_prompt="Break down tasks into actionable plans.",
            inputs=[PortDef(name="task", type_tag="text")],
            outputs=[PortDef(name="plan", type_tag="plan")],
        )

    def _coder_block(self) -> BlockDef:
        """Define the coder block."""
        return BlockDef(
            name="coder",
            role="coder",
            system_prompt="Implement code changes based on specifications.",
            tools=["file_read", "file_write", "shell"],
            inputs=[
                PortDef(name="spec", type_tag="plan"),
                PortDef(name="context", type_tag="files"),
            ],
            outputs=[PortDef(name="changes", type_tag="code-changes")],
            permission=PermissionTier.SCOPED,
        )

    def _reviewer_block(self) -> BlockDef:
        """Define the reviewer block."""
        return BlockDef(
            name="reviewer",
            role="reviewer",
            system_prompt="Review code changes for correctness and quality.",
            inputs=[
                PortDef(name="changes", type_tag="code-changes"),
                PortDef(name="spec", type_tag="plan"),
            ],
            outputs=[PortDef(name="result", type_tag="review")],
        )

    def _tester_block(self) -> BlockDef:
        """Define the tester block."""
        return BlockDef(
            name="tester",
            role="tester",
            system_prompt="Write and run tests for code changes.",
            tools=["file_read", "file_write", "shell"],
            inputs=[
                PortDef(name="changes", type_tag="code-changes"),
                PortDef(name="spec", type_tag="plan"),
            ],
            outputs=[PortDef(name="result", type_tag="test-results")],
            permission=PermissionTier.SCOPED,
        )

    def _evaluator_block(self) -> BlockDef:
        """Define the evaluator block."""
        return BlockDef(
            name="evaluator",
            role="evaluator",
            system_prompt="Evaluate artifacts against quality criteria.",
            inputs=[
                PortDef(name="artifact", type_tag="any"),
                PortDef(name="criteria", type_tag="text"),
            ],
            outputs=[PortDef(name="result", type_tag="review")],
        )

    def _researcher_block(self) -> BlockDef:
        """Define the researcher block."""
        return BlockDef(
            name="researcher",
            role="researcher",
            system_prompt="Research topics and produce detailed reports.",
            tools=["file_read", "shell"],
            inputs=[PortDef(name="question", type_tag="text")],
            outputs=[PortDef(name="report", type_tag="text")],
        )

    def register_block(self, block: BlockDef) -> None:
        """Register a block definition."""
        self._blocks[block.name] = block

    def register_team(self, team: TeamDef) -> None:
        """Register a team definition."""
        self._teams[team.name] = team

    def get_block(self, name: str) -> BlockDef | None:
        """Get a block by name, or None if not found."""
        return self._blocks.get(name)

    def get_team(self, name: str) -> TeamDef | None:
        """Get a team by name, or None if not found."""
        return self._teams.get(name)

    def list_blocks(self) -> list[BlockDef]:
        """List all registered blocks."""
        return list(self._blocks.values())

    def list_teams(self) -> list[TeamDef]:
        """List all registered teams."""
        return list(self._teams.values())

    def load_from_dir(self, blocks_dir: Path) -> int:
        """Load block/team definitions from a directory.

        Returns count of definitions loaded.
        """
        if not blocks_dir.is_dir():
            return 0

        count = 0
        for path in sorted(blocks_dir.glob("*.toml")):
            try:
                count += self._load_toml_file(path)
            except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError):
                logger.debug("Failed to load %s", path, exc_info=True)
        return count

    def _load_toml_file(self, path: Path) -> int:
        """Load a single TOML file. Returns count of definitions loaded."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        count = 0

        if "block" in data:
            block = self._parse_block(data["block"])
            self.register_block(block)
            count += 1

        if "team" in data:
            team = self._parse_team(data["team"])
            self.register_team(team)
            count += 1

        return count

    def _parse_block(self, data: dict[str, Any]) -> BlockDef:
        """Parse a block definition from TOML data."""
        inputs = [
            PortDef(
                name=p["name"],
                type_tag=p.get("type", "any"),
                description=p.get("description", ""),
            )
            for p in data.get("inputs", [])
        ]
        outputs = [
            PortDef(
                name=p["name"],
                type_tag=p.get("type", "any"),
                description=p.get("description", ""),
            )
            for p in data.get("outputs", [])
        ]
        return BlockDef(
            name=data["name"],
            role=data.get("role", data["name"]),
            version=data.get("version", "1.0.0"),
            system_prompt=data.get("system_prompt", ""),
            model=data.get("model"),
            tools=data.get("tools", []),
            inputs=inputs,
            outputs=outputs,
            permission=data.get("permission", PermissionTier.ASK),
            max_retries=data.get("max_retries", 1),
        )

    def _parse_team(self, data: dict[str, Any]) -> TeamDef:
        """Parse a team definition from TOML data."""
        connections = [
            Connection(
                source_block=c["source_block"],
                source_port=c["source_port"],
                target_block=c["target_block"],
                target_port=c["target_port"],
            )
            for c in data.get("connections", [])
        ]
        loops = [
            LoopDef(
                generator_block=lp["generator_block"],
                evaluator_block=lp["evaluator_block"],
                max_iterations=lp.get("max_iterations", 5),
            )
            for lp in data.get("loops", [])
        ]
        return TeamDef(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            blocks=data.get("blocks", {}),
            connections=connections,
            loops=loops,
            entry_block=data.get("entry_block", ""),
        )

    def validate_team(self, team: TeamDef) -> list[str]:
        """Validate a team composition.

        Returns list of errors (empty = valid).
        Checks: blocks exist, port types compatible, entry_block defined,
        loop blocks exist in the team.
        """
        errors: list[str] = []

        if not team.entry_block:
            errors.append("Team must define an entry_block")
        elif team.entry_block not in team.blocks:
            errors.append(f"entry_block '{team.entry_block}' not in team blocks")

        self._validate_block_references(team, errors)
        self._validate_connections(team, errors)
        self._validate_loops(team, errors)

        return errors

    def _validate_block_references(self, team: TeamDef, errors: list[str]) -> None:
        """Verify all referenced block types exist in the registry."""
        for instance_name, block_type in team.blocks.items():
            if self.get_block(block_type) is None:
                errors.append(
                    f"Block type '{block_type}' (instance "
                    f"'{instance_name}') not found in registry"
                )

    def _validate_connections(self, team: TeamDef, errors: list[str]) -> None:
        """Verify all connections reference valid blocks and ports."""
        for conn in team.connections:
            errors.extend(self._validate_connection(conn, team))

    def _validate_loops(self, team: TeamDef, errors: list[str]) -> None:
        """Verify all loop definitions reference valid blocks."""
        for loop in team.loops:
            errors.extend(self._validate_loop(loop, team))

    def _validate_connection(self, conn: Connection, team: TeamDef) -> list[str]:
        """Validate a single connection within a team."""
        errors: list[str] = []

        if conn.source_block not in team.blocks:
            errors.append(f"Connection source '{conn.source_block}' not in team")
            return errors

        if conn.target_block not in team.blocks:
            errors.append(f"Connection target '{conn.target_block}' not in team")
            return errors

        source_block_def = self.get_block(team.blocks[conn.source_block])
        target_block_def = self.get_block(team.blocks[conn.target_block])

        if source_block_def is None or target_block_def is None:
            return errors  # Already reported as missing block type

        source_port = self._find_output_port(source_block_def, conn.source_port)
        target_port = self._find_input_port(target_block_def, conn.target_port)

        if source_port is None:
            errors.append(
                f"Output port '{conn.source_port}' not found on " f"block '{conn.source_block}'"
            )
        if target_port is None:
            errors.append(
                f"Input port '{conn.target_port}' not found on " f"block '{conn.target_block}'"
            )

        if (
            source_port
            and target_port
            and not check_port_compatibility(source_port.type_tag, target_port.type_tag)
        ):
            errors.append(
                f"Port type mismatch: {conn.source_block}."
                f"{conn.source_port} ({source_port.type_tag}) -> "
                f"{conn.target_block}.{conn.target_port} "
                f"({target_port.type_tag})"
            )

        return errors

    def _validate_loop(self, loop: LoopDef, team: TeamDef) -> list[str]:
        """Validate a loop definition within a team."""
        errors: list[str] = []

        if loop.generator_block not in team.blocks:
            errors.append(f"Loop generator '{loop.generator_block}' not in team")
        if loop.evaluator_block not in team.blocks:
            errors.append(f"Loop evaluator '{loop.evaluator_block}' not in team")
        if loop.max_iterations < 1:
            errors.append("Loop max_iterations must be >= 1")

        return errors

    def _find_output_port(self, block: BlockDef, port_name: str) -> PortDef | None:
        """Find an output port by name on a block."""
        for port in block.outputs:
            if port.name == port_name:
                return port
        return None

    def _find_input_port(self, block: BlockDef, port_name: str) -> PortDef | None:
        """Find an input port by name on a block."""
        for port in block.inputs:
            if port.name == port_name:
                return port
        return None
