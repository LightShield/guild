"""RPG fun mode — UI theme with quest log, character sheets, XP (REQ-22)."""

from __future__ import annotations

__all__ = ["RPG_TRANSLATIONS", "rpg_translate"]

RPG_TRANSLATIONS: dict[str, str] = {
    "task": "quest",
    "tasks": "quests",
    "team": "party",
    "teams": "parties",
    "block": "class",
    "blocks": "classes",
    "agent": "hero",
    "agents": "heroes",
    "entry agent": "guild master",
    "learnings": "lore",
    "learning": "lore entry",
    "done": "quest complete",
    "failed": "quest failed",
    "running": "on adventure",
    "idle": "resting",
    "pending": "quest posted",
    "blocked": "cursed",
    "token": "gold",
    "tokens": "gold",
}


def rpg_translate(text: str, enabled: bool = True) -> str:
    """Translate serious terms to RPG equivalents.

    Args:
        text: Text to translate.
        enabled: Whether RPG mode is active.

    Returns:
        Translated text if enabled, original otherwise.
    """
    if not enabled:
        return text
    result = text
    for serious, fun in sorted(RPG_TRANSLATIONS.items(), key=lambda x: -len(x[0])):
        result = result.replace(serious.title(), fun.title())
        result = result.replace(serious, fun)
    return result
