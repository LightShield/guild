"""Tests for skills support (REQ-04.8)."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — used at runtime in test signatures

import pytest

from guild.blocks.skills import SkillDef, SkillRegistry


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
def test_skill_from_markdown_file(tmp_path: Path) -> None:
    """Skills can be loaded from a markdown file."""
    skill_file = tmp_path / "debugging.md"
    skill_file.write_text(
        "---\n"
        "name: debugging\n"
        "description: Advanced debugging techniques\n"
        "tools: [shell, file_read]\n"
        "---\n"
        "\n"
        "# Debugging Skill\n"
        "\n"
        "Use systematic debugging approaches.\n"
    )
    skill = SkillDef.from_file(skill_file)
    assert skill.name == "debugging"
    assert skill.description == "Advanced debugging techniques"
    assert "shell" in skill.tools
    assert "file_read" in skill.tools
    assert "# Debugging Skill" in skill.prompt_content


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
def test_skill_registry_load_from_dir(tmp_path: Path) -> None:
    """SkillRegistry loads all skills from a directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    (skills_dir / "coding.md").write_text(
        "---\n" "name: coding\n" "description: Code generation\n" "---\n" "\n" "Write clean code.\n"
    )
    (skills_dir / "testing.md").write_text(
        "---\n"
        "name: testing\n"
        "description: Test writing\n"
        "---\n"
        "\n"
        "Write comprehensive tests.\n"
    )

    registry = SkillRegistry()
    count = registry.load_from_dir(skills_dir)
    assert count == 2
    assert registry.get("coding") is not None
    assert registry.get("testing") is not None
    assert len(registry.list_skills()) == 2


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
def test_format_skills_for_prompt() -> None:
    """Skills can be formatted for injection into system prompts."""
    registry = SkillRegistry()
    registry.register(
        SkillDef(
            name="research",
            description="Research topics",
            prompt_content="## Research\n\nGather information systematically.",
        )
    )
    registry.register(
        SkillDef(
            name="writing",
            description="Technical writing",
            prompt_content="## Writing\n\nWrite clear documentation.",
        )
    )

    formatted = registry.format_for_prompt(["research", "writing"])
    assert "## Research" in formatted
    assert "## Writing" in formatted
    assert "Gather information systematically." in formatted


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
def test_skill_with_tools() -> None:
    """Skills can provide additional tools."""
    skill = SkillDef(
        name="web-search",
        description="Web searching",
        tools=["web_fetch", "web_search"],
        prompt_content="Use web tools to find information.",
    )
    assert skill.tools == ["web_fetch", "web_search"]

    registry = SkillRegistry()
    registry.register(skill)
    retrieved = registry.get("web-search")
    assert retrieved is not None
    assert retrieved.tools == ["web_fetch", "web_search"]
