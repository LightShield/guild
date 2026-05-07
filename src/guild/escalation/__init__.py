"""Human-in-the-loop escalation system (REQ-15).

Provides an async question queue, presence-aware notifications, and batch
approval for agent-to-human escalation.
"""

from guild.escalation.notify import NotificationChannel, Notifier
from guild.escalation.queue import PendingQuestion, QuestionPriority, QuestionQueue

__all__ = [
    "NotificationChannel",
    "Notifier",
    "PendingQuestion",
    "QuestionPriority",
    "QuestionQueue",
]
