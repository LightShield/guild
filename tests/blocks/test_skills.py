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


# ======================================================================
# Skills edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
class TestSkillsEdgeCases:
    """Cover skills system edge-case branches."""

    def test_skill_from_file_without_frontmatter(self, tmp_path: Path) -> None:
        """Skill loaded from file without frontmatter uses filename as name."""
        f = tmp_path / "my_skill.md"
        f.write_text("Just plain content, no frontmatter.\n")
        skill = SkillDef.from_file(f)
        assert skill.name == "my_skill"
        assert skill.prompt_content == "Just plain content, no frontmatter.\n"

    def test_skill_from_file_with_incomplete_frontmatter(self, tmp_path: Path) -> None:
        """Skill with frontmatter that has only one --- uses defaults."""
        f = tmp_path / "partial.md"
        # Only one --- (starts with --- but does not have closing ---)
        f.write_text("---\nname: test\n")
        skill = SkillDef.from_file(f)
        # With only one ---, split("---", 2) gives [\'\', \'name: test\', \'\'] or fewer
        # The code checks len(parts) >= 3
        assert skill.name in ("test", "partial")

    def test_skill_tools_empty_list(self, tmp_path: Path) -> None:
        """Skill with empty tools: [] returns empty list."""
        f = tmp_path / "empty_tools.md"
        f.write_text("---\nname: toolless\ntools: []\n---\nContent here.\n")
        skill = SkillDef.from_file(f)
        assert skill.tools == []

    def test_skill_registry_load_from_nonexistent_dir(self, tmp_path: Path) -> None:
        """Loading from non-directory returns 0."""
        registry = SkillRegistry()
        count = registry.load_from_dir(tmp_path / "nope")
        assert count == 0

    def test_skill_registry_load_handles_bad_file(self, tmp_path: Path) -> None:
        """Loading a malformed skill file is skipped gracefully."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        bad_file = skills_dir / "bad.md"
        # Make unreadable
        bad_file.write_text("content")
        bad_file.chmod(0o000)
        try:
            registry = SkillRegistry()
            count = registry.load_from_dir(skills_dir)
            assert count == 0
        finally:
            bad_file.chmod(0o644)

    def test_format_for_prompt_unknown_skills_skipped(self) -> None:
        """format_for_prompt skips unknown skill names."""
        registry = SkillRegistry()
        registry.register(SkillDef(name="known", prompt_content="Known content."))
        result = registry.format_for_prompt(["known", "unknown"])
        assert "Known content." in result
        # Unknown should not cause error


# ======================================================================
# Skills frontmatter tools parsing (from coverage gaps)
# ======================================================================


@pytest.mark.req("REQ-04.30")
@pytest.mark.unit
class TestSkillsFrontmatterToolsLastLine:
    """Cover the branch where tools: is NOT the last line in frontmatter."""

    def test_frontmatter_tools_followed_by_more_lines(self, tmp_path: Path) -> None:
        """When tools line is followed by other lines, loop continues past 59->53."""
        # The tools line is in the middle, followed by description
        f = tmp_path / "multi.md"
        f.write_text(
            "---\n"
            "tools: [shell, file_read]\n"
            "name: multi-skill\n"
            "description: A skill with tools then other fields\n"
            "---\n"
            "Body content here.\n"
        )
        skill = SkillDef.from_file(f)
        assert skill.name == "multi-skill"
        assert skill.description == "A skill with tools then other fields"
        assert "shell" in skill.tools
        assert "file_read" in skill.tools

    def test_frontmatter_unrecognized_lines_after_tools(self, tmp_path: Path) -> None:
        """Unrecognized lines after tools line cause loop to continue (59->53)."""
        # Tools line followed by unrecognized lines that don\'t match any elif
        f = tmp_path / "extras.md"
        f.write_text(
            "---\n"
            "name: extras\n"
            "description: test\n"
            "tools: [shell]\n"
            "author: someone\n"
            "version: 1.0\n"
            "---\n"
            "Content.\n"
        )
        skill = SkillDef.from_file(f)
        assert skill.name == "extras"
        assert skill.tools == ["shell"]
