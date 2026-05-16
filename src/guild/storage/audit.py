"""Audit log and decision operations for Guild storage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiosqlite
from logger_python import get_logger

from guild.config.constants import DEFAULT_QUERY_LIMIT

__all__ = ["AuditOps", "DecisionRecord"]

logger = get_logger(__name__)


def _now() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


@dataclass
class DecisionRecord:
    """Record of a non-trivial decision with rationale."""

    decision: str
    rationale: str
    task_id: str | None = None
    agent_id: str | None = None
    alternatives: list[str] | None = None
    reversible: bool = True


class AuditOps:
    """Audit log and decision persistence operations."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        """Initialize with a database connection."""
        self._db = db

    async def log_audit(
        self,
        action: str,
        agent_id: str | None = None,
        details: str | None = None,
    ) -> None:
        """Log an audit event."""
        await self._db.execute(
            "INSERT INTO audit_log (agent_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (agent_id, action, details, _now()),
        )
        await self._db.commit()

    async def list_audit(self, limit: int = DEFAULT_QUERY_LIMIT) -> list[dict[str, Any]]:
        """List audit entries, most recent first."""
        cursor = await self._db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def log_decision(
        self,
        record: DecisionRecord | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        decision: str = "",
        rationale: str = "",
        alternatives: list[str] | None = None,
        *,
        reversible: bool = True,
    ) -> None:
        """Record a non-trivial decision with rationale."""
        if record is None:
            record = DecisionRecord(
                decision=decision,
                rationale=rationale,
                task_id=task_id,
                agent_id=agent_id,
                alternatives=alternatives,
                reversible=reversible,
            )
        alts_json = json.dumps(record.alternatives) if record.alternatives else None
        await self._db.execute(
            "INSERT INTO decisions"
            " (task_id, agent_id, decision, rationale,"
            "  alternatives, reversible, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.task_id,
                record.agent_id,
                record.decision,
                record.rationale,
                alts_json,
                record.reversible,
                _now(),
            ),
        )
        await self._db.commit()

    async def list_decisions(
        self,
        task_id: str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[dict[str, Any]]:
        """List decisions, most recent first, optionally by task."""
        if task_id is None:
            cursor = await self._db.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM decisions" " WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
