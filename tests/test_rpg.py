"""Tests for RPG fun mode (REQ-22)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.rpg import rpg_translate, RPG_TRANSLATIONS


class TestRPGMode:
    """REQ-22: RPG-themed UI skin."""

    def test_translates_task_to_quest(self):
        assert rpg_translate("task") == "quest"

    def test_translates_team_to_party(self):
        assert rpg_translate("team") == "party"

    def test_translates_agent_to_hero(self):
        assert rpg_translate("agent") == "hero"

    def test_preserves_case(self):
        assert rpg_translate("Task") == "Quest"

    def test_disabled_returns_original(self):
        assert rpg_translate("task", enabled=False) == "task"

    def test_translates_status(self):
        assert rpg_translate("done") == "quest complete"
        assert rpg_translate("running") == "on adventure"

    def test_all_translations_defined(self):
        expected_keys = {"task", "team", "block", "agent", "done", "failed", "running", "idle"}
        assert expected_keys <= set(RPG_TRANSLATIONS.keys())
