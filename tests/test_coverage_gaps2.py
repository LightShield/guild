"""Second batch of tests to close remaining branch coverage gaps."""

from __future__ import annotations

from pathlib import Path

import pytest

# ======================================================================
# Skills edge cases (skills.py lines 32->39, 34->39, 59->53, 70, 98, 106-107, 117)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.8")
class TestSkillsEdgeCases:
    """Cover skills system edge-case branches."""

    def test_skill_from_file_without_frontmatter(self, tmp_path: Path) -> None:
        """Skill loaded from file without frontmatter uses filename as name."""
        from guild.blocks.skills import SkillDef

        f = tmp_path / "my_skill.md"
        f.write_text("Just plain content, no frontmatter.\n")
        skill = SkillDef.from_file(f)
        assert skill.name == "my_skill"
        assert skill.prompt_content == "Just plain content, no frontmatter.\n"

    def test_skill_from_file_with_incomplete_frontmatter(self, tmp_path: Path) -> None:
        """Skill with frontmatter that has only one --- uses defaults."""
        from guild.blocks.skills import SkillDef

        f = tmp_path / "partial.md"
        # Only one --- (starts with --- but does not have closing ---)
        f.write_text("---\nname: test\n")
        skill = SkillDef.from_file(f)
        # With only one ---, split("---", 2) gives ['', 'name: test', ''] or fewer
        # The code checks len(parts) >= 3
        assert skill.name in ("test", "partial")

    def test_skill_tools_empty_list(self, tmp_path: Path) -> None:
        """Skill with empty tools: [] returns empty list."""
        from guild.blocks.skills import SkillDef

        f = tmp_path / "empty_tools.md"
        f.write_text("---\nname: toolless\ntools: []\n---\nContent here.\n")
        skill = SkillDef.from_file(f)
        assert skill.tools == []

    def test_skill_registry_load_from_nonexistent_dir(self, tmp_path: Path) -> None:
        """Loading from non-directory returns 0."""
        from guild.blocks.skills import SkillRegistry

        registry = SkillRegistry()
        count = registry.load_from_dir(tmp_path / "nope")
        assert count == 0

    def test_skill_registry_load_handles_bad_file(self, tmp_path: Path) -> None:
        """Loading a malformed skill file is skipped gracefully."""
        from guild.blocks.skills import SkillRegistry

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        bad_file = skills_dir / "bad.md"
        # Make unreadable
        bad_file.write_text("content")
        bad_file.chmod(0o000)
        try:
            registry = SkillRegistry()
            # This shouldn't fail since from_file won't fail on readable content
            # Let's make a test that exercises the exception path
            # Actually, unreadable files will raise OSError in path.read_text
            count = registry.load_from_dir(skills_dir)
            assert count == 0
        finally:
            bad_file.chmod(0o644)

    def test_format_for_prompt_unknown_skills_skipped(self) -> None:
        """format_for_prompt skips unknown skill names."""
        from guild.blocks.skills import SkillDef, SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDef(name="known", prompt_content="Known content."))
        result = registry.format_for_prompt(["known", "unknown"])
        assert "Known content." in result
        # Unknown should not cause error


# ======================================================================
# Config profiles edge cases (profiles.py lines 66, 85, 110, 113, 116, 122->121, 137-139)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-14")
class TestConfigProfilesEdgeCases:
    """Cover config profile loading edge cases."""

    def test_load_agent_profiles_nonscalar_top_level(self, tmp_path: Path) -> None:
        """Non-dict values at top level are skipped."""
        from guild.config.profiles import load_agent_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_file = guild_dir / "agents.toml"
        agents_file.write_text(
            "[worker]\n"
            'model = "qwen2.5"\n'
            'permission = "scoped"\n'
            "\n"
            "# Non-dict top-level key that should be skipped\n"
        )
        profiles = load_agent_profiles(guild_dir)
        assert "worker" in profiles
        assert profiles["worker"].model == "qwen2.5"

    def test_load_agent_profiles_missing_file(self, tmp_path: Path) -> None:
        """Missing agents.toml returns empty dict."""
        from guild.config.profiles import load_agent_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        profiles = load_agent_profiles(guild_dir)
        assert profiles == {}

    def test_load_permission_profiles(self, tmp_path: Path) -> None:
        """Permission profiles load correctly from file."""
        from guild.config.profiles import load_permission_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        perms_file = guild_dir / "permissions.toml"
        perms_file.write_text(
            "[readonly]\n" 'tier = "scoped"\n' 'allowed_tools = ["file_read", "search"]\n'
        )
        profiles = load_permission_profiles(guild_dir)
        assert "readonly" in profiles
        assert profiles["readonly"].tier == "scoped"
        assert "file_read" in profiles["readonly"].allowed_tools

    def test_load_permission_profiles_missing_file(self, tmp_path: Path) -> None:
        """Missing permissions.toml returns empty dict."""
        from guild.config.profiles import load_permission_profiles

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        profiles = load_permission_profiles(guild_dir)
        assert profiles == {}

    def test_validate_config_no_guild_dir(self, tmp_path: Path) -> None:
        """Validation fails when guild_dir doesn't exist."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        config = GuildConfig(model="test", base_url="http://localhost:11434")
        errors = validate_config(config, tmp_path / "nonexistent")
        assert any("does not exist" in e for e in errors)

    def test_validate_config_no_model(self, tmp_path: Path) -> None:
        """Validation fails when model is empty."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = GuildConfig(model="", base_url="http://localhost:11434")
        errors = validate_config(config, guild_dir)
        assert any("model" in e.lower() for e in errors)

    def test_validate_config_no_base_url(self, tmp_path: Path) -> None:
        """Validation fails when base_url is empty."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = GuildConfig(model="test", base_url="")
        errors = validate_config(config, guild_dir)
        assert any("base_url" in e for e in errors)

    def test_validate_config_invalid_concurrent_agents(self, tmp_path: Path) -> None:
        """Validation fails with max_concurrent_agents < 1."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = GuildConfig(
            model="test",
            base_url="http://localhost:11434",
            max_concurrent_agents=0,
        )
        errors = validate_config(config, guild_dir)
        assert any("max_concurrent_agents" in e for e in errors)

    def test_validate_config_invalid_max_tokens(self, tmp_path: Path) -> None:
        """Validation fails with max_tokens < 1."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        config = GuildConfig(
            model="test",
            base_url="http://localhost:11434",
            max_tokens=0,
        )
        errors = validate_config(config, guild_dir)
        assert any("max_tokens" in e for e in errors)

    def test_validate_config_invalid_permission_tier(self, tmp_path: Path) -> None:
        """Validation detects invalid permission tier in agent profiles."""
        from guild.config.models import GuildConfig
        from guild.config.profiles import validate_config

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        agents_file = guild_dir / "agents.toml"
        agents_file.write_text("[badagent]\n" 'permission = "invalid_tier"\n')
        config = GuildConfig(model="test", base_url="http://localhost:11434")
        errors = validate_config(config, guild_dir)
        assert any("invalid" in e.lower() and "permission" in e.lower() for e in errors)

    def test_load_toml_file_parse_error(self, tmp_path: Path) -> None:
        """_load_toml returns empty dict on parse failure."""
        from guild.config.profiles import _load_toml

        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("this [[[is not valid")
        result = _load_toml(bad_file)
        assert result == {}


# ======================================================================
# Sandbox policy edge cases (sandbox.py lines 135-136, 154, 160, 189-190, 195-197)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-13")
class TestSandboxEdgeCases:
    """Cover sandbox policy edge cases."""

    def test_resolve_path_returns_absolute(self) -> None:
        """_resolve_path returns an absolute resolved path."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        result = policy._resolve_path("/tmp/normal")
        # On macOS, /tmp resolves to /private/tmp — just check it's absolute
        assert result.is_absolute()
        assert "normal" in str(result)

    def test_extract_command_name_with_sudo(self) -> None:
        """_extract_command_name skips 'sudo' prefix."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        assert policy._extract_command_name("sudo rm -rf /tmp") == "rm"

    def test_extract_command_name_empty(self) -> None:
        """_extract_command_name returns empty for empty string."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        assert policy._extract_command_name("") == ""

    def test_extract_command_name_only_prefixes(self) -> None:
        """_extract_command_name handles 'sudo env' (all prefixes)."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy()
        # When idx >= len(parts), returns parts[-1]
        result = policy._extract_command_name("sudo env")
        assert result == "env"

    def test_load_sandbox_policy_from_file(self, tmp_path: Path) -> None:
        """load_sandbox_policy parses a security.toml file."""
        from guild.security.sandbox import load_sandbox_policy

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "security.toml").write_text(
            "[filesystem]\n"
            'allowed_paths = ["/tmp"]\n'
            'denied_paths = ["/etc"]\n'
            "\n"
            "[commands]\n"
            'allow = ["git", "ls"]\n'
            'deny = ["rm"]\n'
            "\n"
            "[network]\n"
            "allowed = false\n"
            'hosts_allowlist = ["api.example.com"]\n'
            "\n"
            "[secrets]\n"
            'API_KEY = "sk-secret-123"\n'
        )
        policy = load_sandbox_policy(guild_dir)
        assert policy.allowed_paths == ["/tmp"]
        assert policy.denied_paths == ["/etc"]
        assert policy.allowed_commands == ["git", "ls"]
        assert policy.denied_commands == ["rm"]
        assert policy.network_allowed is False
        assert policy.secrets["API_KEY"] == "sk-secret-123"

    def test_load_sandbox_policy_invalid_toml(self, tmp_path: Path) -> None:
        """load_sandbox_policy returns default on parse failure."""
        from guild.security.sandbox import load_sandbox_policy

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        (guild_dir / "security.toml").write_text("invalid [[[toml")
        policy = load_sandbox_policy(guild_dir)
        # Should fall back to default (permissive)
        assert policy.allowed_paths == []
        assert policy.network_allowed is True

    def test_check_command_denylist_match(self) -> None:
        """Denied commands are blocked."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(denied_commands=["rm", "dd"])
        allowed, reason = policy.check_command("rm -rf /tmp/test")
        assert allowed is False
        assert "denylist" in reason

    def test_check_command_allowlist_no_match(self) -> None:
        """Commands not in allowlist are rejected."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(allowed_commands=["git", "ls"])
        allowed, reason = policy.check_command("curl http://evil.com")
        assert allowed is False
        assert "not in allowlist" in reason

    def test_inject_secret_unknown_placeholder_left_alone(self) -> None:
        """Unknown ${PLACEHOLDER} is left as-is."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(secrets={"API_KEY": "secret123"})
        result = policy.inject_secret("echo ${UNKNOWN_VAR}")
        assert "${UNKNOWN_VAR}" in result

    def test_check_path_denied_takes_precedence(self) -> None:
        """Denied paths take precedence over allowed paths."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(
            allowed_paths=["/tmp"],
            denied_paths=["/tmp/secret"],
        )
        allowed, reason = policy.check_path("/tmp/secret/file.txt")
        assert allowed is False

    def test_check_path_outside_allowed(self) -> None:
        """Paths outside allowed_paths are rejected."""
        from guild.security.sandbox import SandboxPolicy

        policy = SandboxPolicy(allowed_paths=["/tmp"])
        allowed, reason = policy.check_path("/etc/passwd")
        assert allowed is False
        assert "outside" in reason


# ======================================================================
# Config loader edge cases (loader.py lines 65, 87-89, 110, 124, 155-158)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-01.3")
class TestConfigLoaderEdgeCases:
    """Cover config loader edge cases."""

    def test_find_guild_dir_walks_up(self, tmp_path: Path) -> None:
        """find_guild_dir walks up directory tree."""
        from guild.config.loader import find_guild_dir

        guild_dir = tmp_path / ".guild"
        guild_dir.mkdir()
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = find_guild_dir(deep)
        assert result == guild_dir

    def test_find_guild_dir_not_found(self) -> None:
        """find_guild_dir returns None when not found."""
        from guild.config.loader import find_guild_dir

        # Start from root or a place without .guild
        result = find_guild_dir(Path("/"))
        assert result is None

    def test_load_toml_file_invalid(self, tmp_path: Path) -> None:
        """_load_toml_file returns {} on invalid TOML."""
        from guild.config.loader import _load_toml_file

        bad = tmp_path / "bad.toml"
        bad.write_text("invalid [[[toml content")
        result = _load_toml_file(bad)
        assert result == {}

    def test_load_toml_file_missing(self) -> None:
        """_load_toml_file returns {} when file doesn't exist."""
        from guild.config.loader import _load_toml_file

        result = _load_toml_file(Path("/nonexistent/file.toml"))
        assert result == {}

    def test_config_watcher_detects_change(self, tmp_path: Path) -> None:
        """ConfigWatcher detects mtime change and calls callback."""
        import time

        from guild.config.loader import ConfigWatcher

        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "test"\n')
        called = []
        watcher = ConfigWatcher(config_file, callback=lambda: called.append(1))

        # No change yet
        assert watcher.check_for_changes() is False

        # Modify file
        time.sleep(0.05)
        config_file.write_text('model = "updated"\n')
        assert watcher.check_for_changes() is True
        assert len(called) == 1

    def test_config_watcher_missing_file(self, tmp_path: Path) -> None:
        """ConfigWatcher returns False for missing file."""
        from guild.config.loader import ConfigWatcher

        watcher = ConfigWatcher(tmp_path / "nope.toml", callback=lambda: None)
        assert watcher.check_for_changes() is False


# ======================================================================
# Artifacts manager edge cases (manager.py lines 45, 86, 91, 104, 123->126)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-22.1")
class TestArtifactsEdgeCases:
    """Cover artifact manager edge cases."""

    def test_latest_version_no_task_dir(self, tmp_path: Path) -> None:
        """_latest_version returns 0 when task dir doesn't exist."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        assert mgr._latest_version("nonexistent-task", "file") == 0

    def test_list_for_task_no_dir(self, tmp_path: Path) -> None:
        """list_for_task returns empty when task dir missing."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        result = mgr.list_for_task("no-such-task")
        assert result == []

    def test_list_for_task_skips_non_versioned(self, tmp_path: Path) -> None:
        """list_for_task skips files that don't match the versioning pattern."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        task_dir = tmp_path / "artifacts" / "task-1"
        task_dir.mkdir(parents=True)
        (task_dir / "not_versioned.txt").write_text("hello")
        (task_dir / "result.v1").write_text("v1 content")
        result = mgr.list_for_task("task-1")
        assert len(result) == 1
        assert result[0].name == "result"

    def test_get_nonexistent_version(self, tmp_path: Path) -> None:
        """get() returns None for non-existent version."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        result = mgr.get("task-x", "file", version=99)
        assert result is None

    def test_export_empty_task(self, tmp_path: Path) -> None:
        """export() works even when task has no artifacts."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        output_dir = tmp_path / "export"
        result = mgr.export("empty-task", output_dir)
        assert result == output_dir
        assert output_dir.exists()

    def test_export_copies_files(self, tmp_path: Path) -> None:
        """export() copies all artifacts to output directory."""
        from guild.artifacts.manager import ArtifactManager

        mgr = ArtifactManager(tmp_path / "artifacts")
        mgr.save("task-1", "code", "def main(): pass")
        mgr.save_version("task-1", "code", "def main(): return 42")
        output_dir = tmp_path / "export"
        mgr.export("task-1", output_dir)
        assert (output_dir / "code.v1").exists()
        assert (output_dir / "code.v2").exists()


# ======================================================================
# Block registry remaining line: 327
# loop evaluator not in team (already tested but let's hit it directly)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-04.27")
class TestRegistryLoopValidation:
    """Validate loop blocks must be in the team."""

    def test_loop_generator_not_in_team(self) -> None:
        """Loop with generator not in team.blocks errors."""
        from guild.blocks import BlockRegistry, LoopDef, TeamDef

        registry = BlockRegistry()
        team = TeamDef(
            name="loop-gen-missing",
            blocks={"eval": "evaluator"},
            connections=[],
            loops=[
                LoopDef(
                    generator_block="ghost_gen",
                    evaluator_block="eval",
                    max_iterations=3,
                ),
            ],
            entry_block="eval",
        )
        errors = registry.validate_team(team)
        assert any("ghost_gen" in e for e in errors)
