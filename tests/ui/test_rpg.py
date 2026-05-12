"""Tests for RPG mode (REQ-22)."""

import pytest

from guild.ui.rpg import RPGMode


@pytest.mark.unit
def test_rpg_mode_disabled_by_default() -> None:
    """RPG mode is disabled by default."""
    mode = RPGMode()
    assert mode.enabled is False


@pytest.mark.unit
def test_rpg_mode_toggle() -> None:
    """RPG mode can be toggled on."""
    mode = RPGMode(enabled=True)
    assert mode.enabled is True


@pytest.mark.unit
def test_translate_task_to_quest() -> None:
    """'task' is translated to 'quest' in RPG mode."""
    mode = RPGMode(enabled=True)
    assert mode.translate("task") == "quest"
    assert mode.translate("New task created") == "New quest created"


@pytest.mark.unit
def test_translate_agent_to_hero() -> None:
    """'agent' is translated to 'hero' in RPG mode."""
    mode = RPGMode(enabled=True)
    assert mode.translate("agent") == "hero"
    assert mode.translate("agents") == "heroes"


@pytest.mark.unit
def test_translate_no_op_when_disabled() -> None:
    """Translation is a no-op when RPG mode is disabled."""
    mode = RPGMode(enabled=False)
    assert mode.translate("task") == "task"
    assert mode.translate("agent") == "agent"


@pytest.mark.unit
def test_progress_bar_xp_style() -> None:
    """Progress bar uses XP-style formatting."""
    mode = RPGMode(enabled=True)
    assert mode.progress_bar(5, 10) == "[=====-----] 5/10 XP"
    assert mode.progress_bar(10, 10) == "[==========] 10/10 XP"
    assert mode.progress_bar(0, 10) == "[----------] 0/10 XP"
    assert mode.progress_bar(0, 0) == "[----------] 0 XP"


@pytest.mark.unit
def test_quest_log_entry_format() -> None:
    """Tasks are formatted as quest log entries."""
    mode = RPGMode(enabled=True)
    task = {"id": "42", "name": "Fix the bug", "status": "running"}
    entry = mode.quest_log_entry(task)
    assert "Quest #42" in entry
    assert "Fix the bug" in entry
    assert "on adventure" in entry


@pytest.mark.unit
def test_character_sheet_format() -> None:
    """Agent info is formatted as a character sheet."""
    mode = RPGMode(enabled=True)
    agent = {"name": "Coder", "role": "developer", "level": "5", "status": "idle"}
    sheet = mode.character_sheet(agent)
    assert "=== Coder ===" in sheet
    assert "Class: developer" in sheet
    assert "Level: 5" in sheet
    assert "resting" in sheet


@pytest.mark.unit
def test_notification_task_completed() -> None:
    """Task completion gives a celebratory notification."""
    mode = RPGMode(enabled=True)
    msg = mode.notification("task_completed")
    assert msg == "Quest complete! Glory awaits!"


@pytest.mark.unit
def test_notification_stuck() -> None:
    """Stuck event gives a thematic notification."""
    mode = RPGMode(enabled=True)
    msg = mode.notification("stuck")
    assert msg == "The hero is lost in the dungeon..."


@pytest.mark.unit
def test_notification_unknown_event() -> None:
    """Unknown events return the event string itself."""
    mode = RPGMode(enabled=True)
    msg = mode.notification("something_new")
    assert msg == "something_new"
