"""Pluggable skill definitions for agents (REQ-04.8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 — used at runtime

from logger_python import get_logger

__all__ = ["FRONTMATTER_DELIMITER", "SkillDef", "SkillRegistry"]

logger = get_logger(__name__)

FRONTMATTER_DELIMITER = "---"


@dataclass
class SkillDef:
    """A pluggable skill definition."""

    name: str
    description: str = ""
    prompt_content: str = ""  # markdown content injected into agent prompt
    tools: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> SkillDef:
        """Load a skill from a markdown file with optional YAML frontmatter."""
        content = path.read_text(encoding="utf-8")
        name = path.stem
        description = ""
        tools: list[str] = []
        prompt_content = content

        if content.startswith(FRONTMATTER_DELIMITER):
            parts = content.split(FRONTMATTER_DELIMITER, 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                prompt_content = parts[2].strip()
                name, description, tools = _parse_frontmatter(frontmatter, name)

        return cls(
            name=name,
            description=description,
            prompt_content=prompt_content,
            tools=tools,
        )


def _parse_frontmatter(frontmatter: str, default_name: str) -> tuple[str, str, list[str]]:
    """Parse simple YAML-like frontmatter for skill metadata."""
    name = default_name
    description = ""
    tools: list[str] = []

    for line in frontmatter.strip().splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
        elif line.startswith("tools:"):
            raw = line.split(":", 1)[1].strip()
            tools = _parse_tools_list(raw)

    return name, description, tools


def _parse_tools_list(raw: str) -> list[str]:
    """Parse a tools list from frontmatter value."""
    raw = raw.strip("[] ")
    if not raw:
        return []
    return [t.strip().strip("\"'") for t in raw.split(",")]


class SkillRegistry:
    """Manages available skills."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDef] = {}

    def register(self, skill: SkillDef) -> None:
        """Register a skill definition."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDef | None:
        """Get a skill by name, or None if not found."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDef]:
        """List all registered skills."""
        return list(self._skills.values())

    def load_from_dir(self, skills_dir: Path) -> int:
        """Load skills from a directory. Returns count loaded.

        Each .md file in the directory is treated as a skill definition.
        """
        if not skills_dir.is_dir():
            return 0

        count = 0
        for path in sorted(skills_dir.glob("*.md")):
            try:
                skill = SkillDef.from_file(path)
                self.register(skill)
                count += 1
            except (OSError, ValueError, KeyError):
                logger.debug("Failed to load %s", path, exc_info=True)

        return count

    def format_for_prompt(self, skill_names: list[str]) -> str:
        """Format selected skills for injection into system prompt."""
        sections: list[str] = []
        for name in skill_names:
            skill = self.get(name)
            if skill is None:
                continue
            sections.append(skill.prompt_content)
        return "\n\n".join(sections)
