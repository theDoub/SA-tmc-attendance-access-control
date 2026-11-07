"""SQLite connection factory and repository placeholders.

A1 ADR-003 requires SQLite with Write-Ahead Logging. WAL needs a real file, so in-memory
databases are rejected. Schema design and `synchronous` level are TODO(Nhat) (OD-11).
"""

import sqlite3
from pathlib import Path

from tmc_access.domain.errors import StorageError
from tmc_access.domain.models import AccessAttempt, AttendanceRecord


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a file-backed SQLite database in WAL mode."""
    text = str(path)
    if text == ":memory:" or text.startswith("file::memory:") or text == "":
        raise ValueError("A file-backed path is required: WAL is not supported in memory")
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
    if mode != "wal":
        conn.close()
        raise StorageError(f"SQLite refused WAL mode (journal_mode={mode!r})")
    return conn


class SqliteAttendanceRepository:
    """Satisfies `AttendanceRepository`. TODO(Nhat)."""

    def save_attempt(self, attempt: AccessAttempt) -> None:
        raise NotImplementedError("TODO(Nhat)")

    def update_attempt(self, attempt: AccessAttempt) -> None:
        raise NotImplementedError("TODO(Nhat)")

    def save_record_with_outbox(self, record: AttendanceRecord) -> None:
        raise NotImplementedError("TODO(Nhat): record and outbox entry in one transaction")


class SqliteOutboxRepository:
    """Satisfies `OutboxRepository`. TODO(Nhat)."""

    def get_pending(self, batch_size: int) -> list[AttendanceRecord]:
        raise NotImplementedError("TODO(Nhat)")

    def mark_synchronized(self, transaction_ids: list[str]) -> None:
        raise NotImplementedError("TODO(Nhat)")

    def mark_rejected(self, transaction_id: str, reason: str) -> None:
        raise NotImplementedError("TODO(Nhat)")

    def mark_conflict(self, transaction_id: str) -> None:
        raise NotImplementedError("TODO(Nhat)")
