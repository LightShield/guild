"""Block and team definition dataclasses."""

from dataclasses import dataclass, field

from guild.permissions.checker import PermissionTier

__all__ = [
    "BlockDef",
    "Connection",
    "LoopDef",
    "PortDef",
    "TeamDef",
]


@dataclass
class PortDef:
    """Definition of a block input/output port."""

    name: str
    type_tag: str = "any"  # plan, code-changes, review, text, any
    description: str = ""


@dataclass
class BlockDef:
    """Atomic block definition — an agent template."""

    name: str
    role: str
    version: str = "1.0.0"
    system_prompt: str = ""
    provider: str | None = None
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    inputs: list[PortDef] = field(default_factory=list)
    outputs: list[PortDef] = field(default_factory=list)
    permission: str = PermissionTier.ASK
    max_retries: int = 1


@dataclass
class Connection:
    """A connection between two block ports."""

    source_block: str
    source_port: str
    target_block: str
    target_port: str


@dataclass
class LoopDef:
    """Definition of a feedback loop between blocks."""

    generator_block: str
    evaluator_block: str
    max_iterations: int = 5


@dataclass
class TeamDef:
    """A team composition — graph of connected blocks."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    blocks: dict[str, str] = field(default_factory=dict)  # instance_name -> block_type
    connections: list[Connection] = field(default_factory=list)
    loops: list[LoopDef] = field(default_factory=list)
    entry_block: str = ""
