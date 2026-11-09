"""SQLite WAL, attempt persistence and atomic attendance/outbox storage.

A1 ADR-003 requires SQLite with Write-Ahead Logging. WAL needs a real file, so in-memory
databases are rejected. Connections are owned and closed by each repository operation,
so a repository can be injected into request handlers without sharing a SQLite connection.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from tmc_access.domain.errors import StorageError
from tmc_access.domain.models import (
    AccessAttempt,
    AttemptStatus,
    AttendanceRecord,
    ConfirmationEvidence,
    Direction,
    GateAck,
    SyncStatus,
    TimeQuality,
)

_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS access_attempts (
    access_attempt_id TEXT NOT NULL PRIMARY KEY
        CHECK (length(trim(access_attempt_id)) > 0),
    station_id TEXT NOT NULL CHECK (length(trim(station_id)) > 0),
    gate_id TEXT NOT NULL CHECK (length(trim(gate_id)) > 0),
    direction TEXT NOT NULL CHECK (direction IN ('ENTRY', 'EXIT')),
    received_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'RECEIVED' CHECK (status IN (
        'RECEIVED', 'DENIED', 'ALLOWED_PERSISTED', 'UNLOCK_ACKNOWLEDGED',
        'UNLOCK_REJECTED', 'UNLOCK_TIMEOUT', 'PASSAGE_CONFIRMED', 'PASSAGE_UNRESOLVED'
    )),
    subject_id TEXT,
    reason_code TEXT
)
"""

_ATTENDANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS attendance_records (
    transaction_id TEXT NOT NULL PRIMARY KEY,
    access_attempt_id TEXT NOT NULL REFERENCES access_attempts(access_attempt_id),
    employee_id TEXT NOT NULL CHECK (length(trim(employee_id)) > 0),
    factory_id TEXT NOT NULL CHECK (length(trim(factory_id)) > 0),
    station_id TEXT NOT NULL CHECK (length(trim(station_id)) > 0),
    gate_id TEXT NOT NULL CHECK (length(trim(gate_id)) > 0),
    direction TEXT NOT NULL CHECK (direction IN ('ENTRY', 'EXIT')),
    event_time INTEGER NOT NULL,
    confirmation_evidence TEXT NOT NULL CHECK (
        confirmation_evidence IN ('PASSAGE_CONFIRMED', 'CONTROLLER_ACK_ONLY')
    ),
    time_quality TEXT NOT NULL CHECK (time_quality IN ('RELIABLE', 'UNRELIABLE')),
    source_sequence INTEGER NOT NULL CHECK (source_sequence > 0),
    policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
    controller_outcome TEXT NOT NULL CHECK (
        controller_outcome IN ('ACKNOWLEDGED', 'REJECTED', 'TIMEOUT', 'UNAVAILABLE')
    )
)
"""

_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox_events (
    transaction_id TEXT NOT NULL PRIMARY KEY REFERENCES attendance_records(transaction_id),
    sync_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (sync_status IN ('PENDING', 'SYNCED', 'REJECTED', 'CONFLICT')),
    created_at INTEGER NOT NULL,
    rejection_reason TEXT
)
"""

_RECORD_COLUMNS = (
    "transaction_id, access_attempt_id, employee_id, factory_id, station_id, gate_id, "
    "direction, event_time, confirmation_evidence, time_quality, "
    "source_sequence, policy_version, controller_outcome"
)


def _upgrade_attendance_metadata(conn: sqlite3.Connection) -> None:
    """Preserve legacy data without guessing historical policy, sequence or ACK.

    Old rows receive NULL metadata and cannot be returned as complete sync events.
    New writes validate required metadata; historical repair needs real evidence.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(attendance_records)")}
    for name, sql_type in (
        ("source_sequence", "INTEGER"),
        ("policy_version", "TEXT"),
        ("controller_outcome", "TEXT"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE attendance_records ADD COLUMN {name} {sql_type}")


def _upgrade_outbox_reason(conn: sqlite3.Connection) -> None:
    """Add nullable rejection detail without dropping existing queue data."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(outbox_events)")}
    if "rejection_reason" not in columns:
        conn.execute("ALTER TABLE outbox_events ADD COLUMN rejection_reason TEXT")


def _utc_microseconds(value: datetime) -> int:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise StorageError("Persistence timestamps must be timezone-aware datetimes")
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _received_at_microseconds(attempt: AccessAttempt) -> int:
    for value in (attempt.access_attempt_id, attempt.station_id, attempt.gate_id):
        if not isinstance(value, str) or not value.strip():
            raise StorageError("Attempt identifiers must be non-empty strings")
    if not isinstance(attempt.direction, Direction) or not isinstance(
        attempt.status, AttemptStatus
    ):
        raise StorageError("Attempt direction and status must be domain enums")
    for value in (attempt.subject_id, attempt.reason_code):
        if value is not None and not isinstance(value, str):
            raise StorageError("Attempt subject and reason must be strings or None")
    return _utc_microseconds(attempt.received_at)


def _record_values(record: AttendanceRecord) -> tuple[str | int, ...]:
    for value in (
        record.transaction_id,
        record.access_attempt_id,
        record.employee_id,
        record.factory_id,
        record.station_id,
        record.gate_id,
        record.policy_version,
    ):
        if not isinstance(value, str) or not value.strip():
            raise StorageError("Attendance identifiers must be non-empty strings")
    try:
        if UUID(record.transaction_id).version != 4:
            raise ValueError("UUIDv4 required")
    except ValueError as exc:
        raise StorageError("Attendance transaction_id must be a UUIDv4") from exc
    for value, enum_type in (
        (record.direction, Direction),
        (record.confirmation_evidence, ConfirmationEvidence),
        (record.time_quality, TimeQuality),
        (record.sync_status, SyncStatus),
        (record.controller_outcome, GateAck),
    ):
        if not isinstance(value, enum_type):
            raise StorageError("Attendance fields must use domain enums")
    if type(record.source_sequence) is not int or not 0 < record.source_sequence < 2**63:
        raise StorageError("Attendance source_sequence must be a positive SQLite integer")
    if record.confirmation_evidence is ConfirmationEvidence.CONTROLLER_ACK_ONLY:
        raise NotImplementedError("TODO(Nhat/Kim): ACK-only attendance requires OD-05 resolution")
    if record.controller_outcome is not GateAck.ACKNOWLEDGED:
        raise StorageError("Failed or uncertain gate commands are not attendance success")
    return (
        record.transaction_id,
        record.access_attempt_id,
        record.employee_id,
        record.factory_id,
        record.station_id,
        record.gate_id,
        record.direction.value,
        _utc_microseconds(record.event_time),
        record.confirmation_evidence.value,
        record.time_quality.value,
        record.source_sequence,
        record.policy_version,
        record.controller_outcome.value,
    )


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a file-backed SQLite database in WAL mode."""
    text = str(path)
    if text == ":memory:" or text.startswith("file::memory:") or text == "":
        raise ValueError("A file-backed path is required: WAL is not supported in memory")
    conn = None
    try:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=0.1)
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise StorageError("SQLite refused WAL mode")
        return conn
    except (OSError, sqlite3.Error, StorageError) as exc:
        if conn is not None:
            conn.close()
        raise StorageError("Cannot open configured SQLite storage") from exc


class SqliteAttendanceRepository:
    """Attempt writes commit before returning; each call owns its connection.

    The 100 ms lock wait leaves headroom in the 200 ms local-write budget; it is
    not a hard deadline for disk I/O. ACK-only attendance remains pending OD-05.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        try:
            with closing(connect(path)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_ATTEMPT_SCHEMA)
                conn.execute(_ATTENDANCE_SCHEMA)
                _upgrade_attendance_metadata(conn)
                conn.execute(_OUTBOX_SCHEMA)
                _upgrade_outbox_reason(conn)
        except sqlite3.Error as exc:
            raise StorageError("Cannot initialize access attempt storage") from exc

    def save_attempt(self, attempt: AccessAttempt) -> None:
        received_at = _received_at_microseconds(attempt)
        try:
            with closing(connect(self._path)) as conn, conn:
                conn.execute(
                    """INSERT INTO access_attempts
                    (access_attempt_id, station_id, gate_id, direction, received_at,
                     status, subject_id, reason_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        attempt.access_attempt_id,
                        attempt.station_id,
                        attempt.gate_id,
                        attempt.direction.value,
                        received_at,
                        attempt.status.value,
                        attempt.subject_id,
                        attempt.reason_code,
                    ),
                )
        except sqlite3.Error as exc:
            raise StorageError("Cannot persist access attempt") from exc

    def update_attempt(self, attempt: AccessAttempt) -> None:
        received_at = _received_at_microseconds(attempt)
        try:
            with closing(connect(self._path)) as conn, conn:
                cursor = conn.execute(
                    """UPDATE access_attempts SET status=?, subject_id=?, reason_code=?
                    WHERE access_attempt_id=? AND station_id=? AND gate_id=?
                    AND direction=? AND received_at=?""",
                    (
                        attempt.status.value,
                        attempt.subject_id,
                        attempt.reason_code,
                        attempt.access_attempt_id,
                        attempt.station_id,
                        attempt.gate_id,
                        attempt.direction.value,
                        received_at,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Attempt does not exist or immutable fields differ")
        except sqlite3.Error as exc:
            raise StorageError("Cannot update access attempt") from exc

    def save_record_with_outbox(self, record: AttendanceRecord) -> None:
        values = _record_values(record)
        try:
            with closing(connect(self._path)) as conn, conn:
                # Serialize the duplicate check and insert across independent writers.
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM attendance_records WHERE transaction_id=?",
                    (record.transaction_id,),
                ).fetchone()
                if existing is not None:
                    if existing != values:
                        raise StorageError("Attendance identifier has conflicting content")
                    if (
                        conn.execute(
                            "SELECT 1 FROM outbox_events WHERE transaction_id=?",
                            (record.transaction_id,),
                        ).fetchone()
                        is None
                    ):
                        raise StorageError("Stored attendance is missing its outbox entry")
                    return  # Preserve current sync state and original queue timestamp.
                if record.sync_status is not SyncStatus.PENDING:
                    raise StorageError("New attendance must start PENDING")
                conn.execute(
                    f"INSERT INTO attendance_records ({_RECORD_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                conn.execute(
                    "INSERT INTO outbox_events (transaction_id, sync_status, created_at) "
                    "VALUES (?, ?, ?)",
                    (
                        record.transaction_id,
                        SyncStatus.PENDING.value,
                        _utc_microseconds(datetime.now(UTC)),
                    ),
                )
        except sqlite3.Error as exc:
            raise StorageError("Cannot persist attendance and outbox atomically") from exc


class SqliteOutboxRepository:
    """Durable queue states. Callers supply only IDs actually accepted by the Hub.

    Transitions are PENDING -> SYNCED/REJECTED/CONFLICT. Repeating the same
    terminal state is a no-op; a different terminal state raises StorageError.
    This repository persists acknowledgements, but does not contact the Hub.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get_pending(self, batch_size: int) -> list[AttendanceRecord]:
        if type(batch_size) is not int or batch_size <= 0:
            raise StorageError("Outbox batch_size must be a positive integer")
        columns = ", ".join(f"a.{name.strip()}" for name in _RECORD_COLUMNS.split(","))
        try:
            with closing(connect(self._path)) as conn:
                rows = conn.execute(
                    f"SELECT {columns}, o.sync_status FROM attendance_records a "
                    "JOIN outbox_events o ON a.transaction_id=o.transaction_id "
                    "WHERE o.sync_status='PENDING' "
                    "ORDER BY o.created_at, o.transaction_id LIMIT ?",
                    (batch_size,),
                ).fetchall()
            if any(
                type(row[10]) is not int
                or not 0 < row[10] < 2**63
                or not isinstance(row[11], str)
                or not row[11].strip()
                for row in rows
            ):
                raise StorageError("Pending attendance has missing or invalid A1 metadata")
            return [
                AttendanceRecord(
                    transaction_id=row[0],
                    access_attempt_id=row[1],
                    employee_id=row[2],
                    factory_id=row[3],
                    station_id=row[4],
                    gate_id=row[5],
                    direction=Direction(row[6]),
                    event_time=datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=row[7]),
                    confirmation_evidence=ConfirmationEvidence(row[8]),
                    time_quality=TimeQuality(row[9]),
                    source_sequence=row[10],
                    policy_version=row[11],
                    controller_outcome=GateAck(row[12]),
                    sync_status=SyncStatus(row[13]),
                )
                for row in rows
            ]
        except (sqlite3.Error, ValueError, TypeError, OverflowError) as exc:
            raise StorageError("Cannot read pending attendance events") from exc

    def mark_synchronized(self, transaction_ids: list[str]) -> None:
        if not isinstance(transaction_ids, list):
            raise StorageError("Accepted IDs must be a list")
        self._mark(transaction_ids, SyncStatus.SYNCED)

    def mark_rejected(self, transaction_id: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise StorageError("Permanent rejection requires a non-empty reason")
        self._mark([transaction_id], SyncStatus.REJECTED, reason)

    def mark_conflict(self, transaction_id: str) -> None:
        self._mark([transaction_id], SyncStatus.CONFLICT)

    def _mark(
        self, transaction_ids: list[str], status: SyncStatus, reason: str | None = None
    ) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in transaction_ids):
            raise StorageError("Outbox identifiers must be non-empty strings")
        if not transaction_ids:
            return
        try:
            with closing(connect(self._path)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                _upgrade_outbox_reason(conn)
                for transaction_id in dict.fromkeys(transaction_ids):
                    row = conn.execute(
                        "SELECT sync_status FROM outbox_events WHERE transaction_id=?",
                        (transaction_id,),
                    ).fetchone()
                    if row is None:
                        raise StorageError("Cannot update an unknown outbox event")
                    if row[0] == status.value:
                        continue  # Preserve original rejection reason on repeated delivery results.
                    if row[0] != SyncStatus.PENDING.value:
                        raise StorageError("Cannot change an existing terminal outbox state")
                    conn.execute(
                        "UPDATE outbox_events SET sync_status=?, rejection_reason=? "
                        "WHERE transaction_id=?",
                        (status.value, reason, transaction_id),
                    )
        except sqlite3.Error as exc:
            raise StorageError("Cannot persist outbox delivery status") from exc
