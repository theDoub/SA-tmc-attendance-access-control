"""Real file-backed attempt persistence; no attendance/outbox implementation implied."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tmc_access.domain.errors import StorageError
from tmc_access.domain.models import AccessAttempt, AttemptStatus, Direction
from tmc_access.infrastructure.persistence.sqlite import SqliteAttendanceRepository, connect

pytestmark = pytest.mark.integration


@pytest.fixture
def attempt() -> AccessAttempt:
    return AccessAttempt(
        access_attempt_id="synthetic-attempt",
        station_id="synthetic-station",
        gate_id="synthetic-gate",
        direction=Direction.ENTRY,
        received_at=datetime(2026, 11, 9, 10, 30, 0, 123456, tzinfo=timezone(timedelta(hours=7))),
    )


@pytest.fixture
def storage(tmp_path):
    path = tmp_path / "edge.db"
    return SqliteAttendanceRepository(path), path


def read_attempt(path, attempt_id="synthetic-attempt"):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM access_attempts WHERE access_attempt_id=?", (attempt_id,)
        ).fetchone()
        return dict(row) if row else None


def test_schema_has_only_primary_key_index(storage) -> None:
    _, path = storage
    with closing(sqlite3.connect(path)) as conn:
        assert [row[1] for row in conn.execute("PRAGMA table_info(access_attempts)")] == [
            "access_attempt_id",
            "station_id",
            "gate_id",
            "direction",
            "received_at",
            "status",
            "subject_id",
            "reason_code",
        ]
        indexes = conn.execute("PRAGMA index_list(access_attempts)").fetchall()
        assert len(indexes) == 1
        assert indexes[0][3] == "pk"


def test_save_is_durable_and_preserves_utc_microseconds(storage, attempt) -> None:
    repo, path = storage
    repo.save_attempt(attempt)
    # Every operation closes its connection; a new repository can reopen the database.
    SqliteAttendanceRepository(path)
    row = read_attempt(path)
    assert row == {
        "access_attempt_id": attempt.access_attempt_id,
        "station_id": attempt.station_id,
        "gate_id": attempt.gate_id,
        "direction": "ENTRY",
        "received_at": 1794195000123456,
        "status": "RECEIVED",
        "subject_id": None,
        "reason_code": None,
    }


@pytest.mark.parametrize("status", list(AttemptStatus))
def test_update_mutable_fields_preserves_original_scan(storage, attempt, status) -> None:
    repo, path = storage
    repo.save_attempt(attempt)
    before = read_attempt(path)
    repo.update_attempt(
        replace(attempt, status=status, subject_id="synthetic-subject", reason_code="SYNTHETIC")
    )
    after = read_attempt(path)
    assert after == {
        **before,
        "status": status.value,
        "subject_id": "synthetic-subject",
        "reason_code": "SYNTHETIC",
    }


def test_denied_unknown_subject_can_be_saved(storage, attempt) -> None:
    repo, path = storage
    repo.save_attempt(replace(attempt, status=AttemptStatus.DENIED, reason_code="QR_REJECTED"))
    assert read_attempt(path)["subject_id"] is None
    assert read_attempt(path)["reason_code"] == "QR_REJECTED"


def test_duplicate_insert_preserves_existing_row_and_repository_recovers(storage, attempt) -> None:
    repo, path = storage
    repo.save_attempt(attempt)
    with pytest.raises(StorageError):
        repo.save_attempt(replace(attempt, status=AttemptStatus.DENIED))
    assert read_attempt(path)["status"] == "RECEIVED"
    repo.save_attempt(replace(attempt, access_attempt_id="synthetic-second"))
    assert read_attempt(path, "synthetic-second") is not None


def test_update_missing_attempt_does_not_insert(storage, attempt) -> None:
    repo, path = storage
    with pytest.raises(StorageError):
        repo.update_attempt(attempt)
    assert read_attempt(path) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"station_id": "synthetic-other"},
        {"gate_id": "synthetic-other"},
        {"direction": Direction.EXIT},
        {"received_at": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
)
def test_update_rejects_changed_immutable_fields(storage, attempt, changes) -> None:
    repo, path = storage
    repo.save_attempt(attempt)
    before = read_attempt(path)
    with pytest.raises(StorageError):
        repo.update_attempt(replace(attempt, status=AttemptStatus.DENIED, **changes))
    assert read_attempt(path) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"access_attempt_id": " "},
        {"station_id": ""},
        {"gate_id": None},
        {"direction": "ENTRY"},
        {"status": "UNKNOWN"},
        {"received_at": datetime(2026, 11, 9)},
        {"subject_id": 123},
        {"reason_code": 123},
    ],
)
def test_invalid_attempt_never_writes(storage, attempt, changes) -> None:
    repo, path = storage
    with pytest.raises(StorageError):
        repo.save_attempt(replace(attempt, **changes))
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM access_attempts").fetchone()[0] == 0


def test_write_lock_failure_leaves_no_row_and_can_retry(storage, attempt) -> None:
    repo, path = storage
    with closing(connect(path)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(StorageError):
                repo.save_attempt(attempt)
            assert read_attempt(path) is None
        finally:
            blocker.rollback()
    repo.save_attempt(attempt)
    assert read_attempt(path) is not None


@pytest.mark.parametrize("operation", ["save", "update"])
def test_commit_failure_rolls_back_all_changes(storage, attempt, operation) -> None:
    repo, path = storage
    if operation == "update":
        repo.save_attempt(attempt)
    before = read_attempt(path)
    # A real deferred FK violation fails at COMMIT, after the write/trigger succeeded.
    with closing(connect(path)) as conn, conn:
        conn.execute("CREATE TABLE synthetic_parent (id INTEGER PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE synthetic_child (
                parent_id INTEGER REFERENCES synthetic_parent(id) DEFERRABLE INITIALLY DEFERRED
            )"""
        )
        event = "INSERT" if operation == "save" else "UPDATE"
        conn.execute(
            f"""CREATE TRIGGER synthetic_commit_failure AFTER {event} ON access_attempts
                BEGIN INSERT INTO synthetic_child VALUES (1); END"""
        )
    with pytest.raises(StorageError):
        if operation == "save":
            repo.save_attempt(attempt)
        else:
            repo.update_attempt(replace(attempt, status=AttemptStatus.DENIED))
    assert read_attempt(path) == before
    with closing(connect(path)) as conn, conn:
        assert conn.execute("SELECT count(*) FROM synthetic_child").fetchone()[0] == 0
        conn.execute("DROP TRIGGER synthetic_commit_failure")
    if operation == "save":
        repo.save_attempt(attempt)
    else:
        repo.update_attempt(replace(attempt, status=AttemptStatus.DENIED))


def test_repository_can_be_called_from_request_thread(storage, attempt) -> None:
    repo, path = storage
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(repo.save_attempt, attempt).result()
        pool.submit(repo.update_attempt, replace(attempt, status=AttemptStatus.DENIED)).result()
    assert read_attempt(path)["status"] == "DENIED"


def test_open_failure_is_storage_error(tmp_path) -> None:
    with pytest.raises(StorageError):
        SqliteAttendanceRepository(tmp_path)  # A directory cannot be opened as the DB file.


def test_sql_parameters_are_not_interpreted_as_sql(storage, attempt) -> None:
    repo, path = storage
    reason = "synthetic'; DROP TABLE access_attempts; --"
    repo.save_attempt(replace(attempt, reason_code=reason))
    assert read_attempt(path)["reason_code"] == reason
