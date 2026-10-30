"""Persistent, restart-safe daily request quotas.

The in-process client rate limiter smooths bursts; it cannot enforce a *daily*
budget because a restart resets it. This store keeps the counter in SQLite so a
crashed or redeployed server neither forgets the usage nor lets a caller reset
it by reconnecting.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.storage.db import connect, init_database

SCHEMA = """
CREATE TABLE IF NOT EXISTS request_quota (
    subject TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subject, day)
);
CREATE INDEX IF NOT EXISTS request_quota_day ON request_quota(day);
"""


class QuotaError(RuntimeError):
    """The quota store is unavailable; callers must fail closed."""


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    used: int
    limit: int
    remaining: int
    retry_after_seconds: int


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).date()


def _seconds_until_tomorrow(now: datetime) -> int:
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max(1, int((tomorrow - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()))


class QuotaStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _connection(self) -> sqlite3.Connection:
        try:
            connection = connect(self.path)
            connection.executescript(SCHEMA)
            return connection
        except sqlite3.Error as exc:
            raise QuotaError("quota store could not be opened") from exc

    def consume(
        self,
        subject: str,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> QuotaDecision:
        """Atomically take one unit for ``subject`` on the current UTC day.

        ``limit <= 0`` means unlimited and never writes a row.
        """
        if limit <= 0:
            return QuotaDecision(True, 0, 0, 0, 0)
        if not subject:
            raise QuotaError("quota subject is required")
        moment = now or datetime.now(timezone.utc)
        day = _today(moment).isoformat()
        stamp = moment.isoformat()
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT used FROM request_quota WHERE subject=? AND day=?",
                    (subject, day),
                ).fetchone()
                used = int(row["used"]) if row else 0
                if used >= limit:
                    connection.rollback()
                    return QuotaDecision(False, used, limit, 0, _seconds_until_tomorrow(moment))
                connection.execute(
                    "INSERT INTO request_quota (subject, day, used, updated_at)"
                    " VALUES (?, ?, 1, ?)"
                    " ON CONFLICT(subject, day) DO UPDATE SET"
                    " used = used + 1, updated_at = excluded.updated_at",
                    (subject, day, stamp),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise QuotaError("quota check failed") from exc
        return QuotaDecision(True, used + 1, limit, max(0, limit - used - 1), 0)

    def usage(self, subject: str, *, now: datetime | None = None) -> int:
        day = _today(now).isoformat()
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT used FROM request_quota WHERE subject=? AND day=?",
                    (subject, day),
                ).fetchone()
        except sqlite3.Error as exc:
            raise QuotaError("quota lookup failed") from exc
        return int(row["used"]) if row else 0

    def prune(self, *, keep_days: int = 7, now: datetime | None = None) -> int:
        """Drop old rows so the table does not grow without bound."""
        cutoff = (_today(now) - timedelta(days=keep_days)).isoformat()
        try:
            with self._connection() as connection:
                cursor = connection.execute("DELETE FROM request_quota WHERE day < ?", (cutoff,))
                connection.commit()
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise QuotaError("quota prune failed") from exc
