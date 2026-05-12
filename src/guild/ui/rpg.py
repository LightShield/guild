"""RPG theme for CLI output (REQ-22)."""

from __future__ import annotations

__all__ = ["RPG_TRANSLATIONS", "RPGMode"]

RPG_TRANSLATIONS: dict[str, str] = {
    "task": "quest",
    "tasks": "quests",
    "team": "party",
    "agent": "hero",
    "agents": "heroes",
    "block": "class",
    "blocks": "classes",
    "learnings": "lore",
    "done": "quest complete",
    "failed": "quest failed",
    "running": "on adventure",
    "idle": "resting",
    "pending": "quest posted",
    "token": "gold",
    "tokens": "gold",
}

_NOTIFICATIONS: dict[str, str] = {
    "task_created": "A new quest has arrived!",
    "task_completed": "Quest complete! Glory awaits!",
    "task_failed": "The quest has failed... regroup and try again.",
    "agent_started": "A hero enters the fray!",
    "stuck": "The hero is lost in the dungeon...",
    "escalation": "Summoning a more powerful ally!",
}


class RPGMode:
    """RPG theme for CLI output."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def translate(self, text: str) -> str:
        """Apply RPG translations to text. No-op if disabled."""
        if not self.enabled:
            return text
        result = text
        for serious, fun in sorted(RPG_TRANSLATIONS.items(), key=lambda x: -len(x[0])):
            result = result.replace(serious.title(), fun.title())
            result = result.replace(serious, fun)
        return result

    def progress_bar(self, current: int, total: int) -> str:
        """XP-style progress bar."""
        if total <= 0:
            return "[----------] 0 XP"
        filled = min(10, (current * 10) // total)
        bar = "=" * filled + "-" * (10 - filled)
        return f"[{bar}] {current}/{total} XP"

    def quest_log_entry(self, task: dict[str, str]) -> str:
        """Format a task as a quest log entry."""
        name = task.get("name", "Unknown Quest")
        status = task.get("status", "pending")
        rpg_status = self.translate(status) if self.enabled else status
        task_id = task.get("id", "???")
        return f"[Quest #{task_id}] {name} — {rpg_status}"

    def character_sheet(self, agent: dict[str, str]) -> str:
        """Format agent info as an RPG character sheet."""
        name = agent.get("name", "Unknown")
        role = agent.get("role", "adventurer")
        level = agent.get("level", "1")
        status = agent.get("status", "idle")
        rpg_status = self.translate(status) if self.enabled else status
        lines = [
            f"=== {name} ===",
            f"  Class: {role}",
            f"  Level: {level}",
            f"  Status: {rpg_status}",
        ]
        return "\n".join(lines)

    def notification(self, event: str) -> str:
        """RPG-style notification message."""
        return _NOTIFICATIONS.get(event, event)

    def level_up(self, new_level: int) -> str:
        """Generate a Level Up! milestone notification.

        Args:
            new_level: The new level reached.

        Returns:
            A themed notification string.
        """
        if self.enabled:
            return f"Level Up! You have reached Level {new_level}! Glory awaits!"
        return f"Milestone reached: level {new_level}"
