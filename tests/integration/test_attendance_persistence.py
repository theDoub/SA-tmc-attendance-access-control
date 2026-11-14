"""Attendance + outbox atomicity, durable pending reads and stable event identity."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

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
from tmc_access.infrastructure.persistence.sqlite import (
    SqliteAttendanceRepository,
    SqliteOutboxRepository,
    connect,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def storage(tmp_path):
    path = tmp_path / "edge.db"
    repo = SqliteAttendanceRepository(path)
    repo.save_attempt(
        AccessAttempt(
            "synthetic-attempt",
            "synthetic-station",
            "synthetic-gate",
            Direction.ENTRY,
            datetime(2026, 11, 9, tzinfo=UTC),
            status=AttemptStatus.PASSAGE_CONFIRMED,
            subject_id="synthetic-subject",
        )
    )
    return repo, SqliteOutboxRepository(path), path


@pytest.fixture
def record() -> AttendanceRecord:
    return AttendanceRecord(
        transaction_id=str(uuid4()),
        access_attempt_id="synthetic-attempt",
        employee_id="synthetic-subject",
        factory_id="synthetic-factory",
        station_id="synthetic-station",
        gate_id="synthetic-gate",
        direction=Direction.ENTRY,
        event_time=datetime(2026, 11, 9, 7, 0, 0, 123456, tzinfo=timezone(timedelta(hours=7))),
        confirmation_evidence=ConfirmationEvidence.PASSAGE_CONFIRMED,
        source_sequence=1,
        policy_version="synthetic-policy-v1",
        controller_ack=GateAck.ACKNOWLEDGED,
    )


def snapshot(path):
    with closing(sqlite3.connect(path)) as conn:
        return (
            conn.execute("SELECT * FROM attendance_records ORDER BY transaction_id").fetchall(),
            conn.execute("SELECT * FROM outbox_events ORDER BY transaction_id").fetchall(),
        )


def test_save_creates_both_rows_and_recovers_pending_after_reopen(storage, record) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    assert tuple(map(len, snapshot(path))) == (1, 1)
    expected = replace(record, event_time=record.event_time.astimezone(UTC))
    assert outbox.get_pending(10) == [expected]
    SqliteAttendanceRepository(path)
    recovered = SqliteOutboxRepository(path).get_pending(10)
    assert recovered == [expected]
    assert recovered[0].transaction_id == record.transaction_id
    assert recovered[0].sync_status is SyncStatus.PENDING


def test_fresh_process_recovers_original_pending_id(storage, record) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    script = """
import sys
from tmc_access.infrastructure.persistence.sqlite import SqliteOutboxRepository
events = SqliteOutboxRepository(sys.argv[1]).get_pending(10)
assert len(events) == 1
print(events[0].transaction_id, events[0].sync_status.value)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == f"{record.transaction_id} PENDING"


def test_same_id_and_content_is_idempotent(storage, record) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    repo.save_record_with_outbox(replace(record, event_time=record.event_time.astimezone(UTC)))
    assert snapshot(path) == before


@pytest.mark.parametrize("status", [SyncStatus.SYNCED, SyncStatus.REJECTED, SyncStatus.CONFLICT])
def test_resave_does_not_reset_delivery_state(storage, record, status) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    # Direct SQL sets up later delivery states; status-writing API is a future task.
    with closing(connect(path)) as conn, conn:
        conn.execute("UPDATE outbox_events SET sync_status=?", (status.value,))
    before = snapshot(path)
    repo.save_record_with_outbox(record)
    repo.save_record_with_outbox(replace(record, sync_status=status))
    assert snapshot(path) == before
    assert outbox.get_pending(10) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"employee_id": "synthetic-other"},
        {"direction": Direction.EXIT},
        {"time_quality": TimeQuality.UNRELIABLE},
        {"event_time": datetime(2026, 11, 10, tzinfo=UTC)},
    ],
)
def test_conflicting_id_never_overwrites_existing_event(storage, record, changes) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with pytest.raises(StorageError, match="conflicting"):
        repo.save_record_with_outbox(replace(record, **changes))
    assert snapshot(path) == before


def test_missing_attempt_rolls_back(storage, record) -> None:
    repo, _, path = storage
    with pytest.raises(StorageError):
        repo.save_record_with_outbox(replace(record, access_attempt_id="synthetic-missing"))
    assert snapshot(path) == ([], [])


@pytest.mark.parametrize("failure", ["insert", "commit"])
def test_outbox_failure_rolls_back_attendance_too(storage, record, failure) -> None:
    repo, _, path = storage
    with closing(connect(path)) as conn, conn:
        if failure == "insert":
            conn.execute(
                """CREATE TRIGGER synthetic_failure BEFORE INSERT ON outbox_events
                BEGIN SELECT RAISE(ABORT, 'synthetic outbox failure'); END"""
            )
        else:
            conn.execute("CREATE TABLE synthetic_parent (id INTEGER PRIMARY KEY)")
            conn.execute(
                """CREATE TABLE synthetic_child (id INTEGER REFERENCES synthetic_parent(id)
                DEFERRABLE INITIALLY DEFERRED)"""
            )
            conn.execute(
                """CREATE TRIGGER synthetic_failure AFTER INSERT ON outbox_events
                BEGIN INSERT INTO synthetic_child VALUES (1); END"""
            )
    with pytest.raises(StorageError):
        repo.save_record_with_outbox(record)
    assert snapshot(path) == ([], [])
    with closing(connect(path)) as conn, conn:
        conn.execute("DROP TRIGGER synthetic_failure")
    repo.save_record_with_outbox(record)
    assert tuple(map(len, snapshot(path))) == (1, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"transaction_id": "synthetic-not-a-uuid"},
        {"transaction_id": "00000000-0000-1000-8000-000000000000"},
        {"employee_id": ""},
        {"factory_id": " "},
        {"event_time": datetime(2026, 11, 9)},
        {"direction": "ENTRY"},
        {"confirmation_evidence": "PASSAGE_CONFIRMED"},
        {"time_quality": "RELIABLE"},
        {"sync_status": SyncStatus.SYNCED},
    ],
)
def test_invalid_new_attendance_writes_neither_row(storage, record, changes) -> None:
    repo, _, path = storage
    with pytest.raises((StorageError, ValueError)):
        repo.save_record_with_outbox(replace(record, **changes))
    assert snapshot(path) == ([], [])


def test_ack_only_is_explicitly_unimplemented(storage, record) -> None:
    repo, _, path = storage
    with pytest.raises(NotImplementedError, match="OD-05"):
        repo.save_record_with_outbox(
            replace(record, confirmation_evidence=ConfirmationEvidence.CONTROLLER_ACK_ONLY)
        )
    assert snapshot(path) == ([], [])


def test_pending_batch_limit_order_and_excluded_statuses(storage, record) -> None:
    repo, outbox, path = storage
    records = [replace(record, transaction_id=str(uuid4())) for _ in range(4)]
    for position, event in enumerate(records):
        repo.save_record_with_outbox(event)
        with closing(connect(path)) as conn, conn:
            conn.execute(
                "UPDATE outbox_events SET created_at=? WHERE transaction_id=?",
                (position, event.transaction_id),
            )
    assert [r.transaction_id for r in outbox.get_pending(2)] == [
        r.transaction_id for r in records[:2]
    ]
    with closing(connect(path)) as conn, conn:
        for event, status in zip(records, ["SYNCED", "REJECTED", "CONFLICT"], strict=False):
            conn.execute(
                "UPDATE outbox_events SET sync_status=? WHERE transaction_id=?",
                (status, event.transaction_id),
            )
    assert [r.transaction_id for r in outbox.get_pending(10)] == [records[3].transaction_id]


@pytest.mark.parametrize("size", [0, -1, True, 1.5, "10"])
def test_invalid_batch_size_fails(storage, size) -> None:
    _, outbox, _ = storage
    with pytest.raises(StorageError):
        outbox.get_pending(size)


def test_concurrent_resaves_create_one_event(storage, record) -> None:
    repo, _, path = storage
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(repo.save_record_with_outbox, record) for _ in range(2)]
        for future in futures:
            future.result()
    assert tuple(map(len, snapshot(path))) == (1, 1)


def test_corrupt_pending_event_is_storage_error(storage, record) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    with closing(connect(path)) as conn, conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE attendance_records SET time_quality='synthetic-invalid'")
    with pytest.raises(StorageError):
        outbox.get_pending(10)


def test_missing_outbox_is_not_silently_repaired(storage, record) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    with closing(connect(path)) as conn, conn:
        conn.execute("DELETE FROM outbox_events")
    with pytest.raises(StorageError, match="missing"):
        repo.save_record_with_outbox(record)
    assert tuple(map(len, snapshot(path))) == (1, 0)


def mark_status(outbox, transaction_id, status):
    if status is SyncStatus.SYNCED:
        outbox.mark_synchronized([transaction_id])
    elif status is SyncStatus.REJECTED:
        outbox.mark_rejected(transaction_id, "SYNTHETIC_INVALID_EVENT")
    else:
        outbox.mark_conflict(transaction_id)


@pytest.mark.parametrize("status", [SyncStatus.SYNCED, SyncStatus.REJECTED, SyncStatus.CONFLICT])
def test_terminal_status_persists_and_resave_does_not_requeue(storage, record, status) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    mark_status(outbox, record.transaction_id, status)
    before = snapshot(path)
    mark_status(outbox, record.transaction_id, status)
    repo.save_record_with_outbox(record)
    SqliteAttendanceRepository(path)
    assert SqliteOutboxRepository(path).get_pending(10) == []
    assert snapshot(path) == before
    assert before[1][0][1] == status.value
    assert before[1][0][3] == ("SYNTHETIC_INVALID_EVENT" if status is SyncStatus.REJECTED else None)
    assert len(before[0]) == 1  # Attendance is retained for every delivery outcome.


def test_only_accepted_ids_are_marked_and_duplicate_ack_is_idempotent(storage, record) -> None:
    repo, outbox, path = storage
    other = replace(record, transaction_id=str(uuid4()))
    repo.save_record_with_outbox(record)
    repo.save_record_with_outbox(other)
    outbox.mark_synchronized([record.transaction_id, record.transaction_id])
    assert [event.transaction_id for event in outbox.get_pending(10)] == [other.transaction_id]
    before = snapshot(path)
    outbox.mark_synchronized([record.transaction_id])
    outbox.mark_synchronized([])
    assert snapshot(path) == before


def test_unknown_id_rolls_back_entire_accepted_batch(storage, record) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with pytest.raises(StorageError, match="unknown"):
        outbox.mark_synchronized([record.transaction_id, str(uuid4())])
    assert snapshot(path) == before


@pytest.mark.parametrize("status", [SyncStatus.SYNCED, SyncStatus.REJECTED, SyncStatus.CONFLICT])
@pytest.mark.parametrize("target", [SyncStatus.SYNCED, SyncStatus.REJECTED, SyncStatus.CONFLICT])
def test_conflicting_terminal_result_cannot_overwrite(storage, record, status, target) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    mark_status(outbox, record.transaction_id, status)
    before = snapshot(path)
    if target is status:
        mark_status(outbox, record.transaction_id, target)
    else:
        with pytest.raises(StorageError, match="terminal"):
            mark_status(outbox, record.transaction_id, target)
    assert snapshot(path) == before


def test_rejected_item_does_not_block_other_pending_events(storage, record) -> None:
    repo, outbox, path = storage
    other = replace(record, transaction_id=str(uuid4()))
    repo.save_record_with_outbox(record)
    repo.save_record_with_outbox(other)
    reason = "synthetic'; DROP TABLE outbox_events; --"
    outbox.mark_rejected(record.transaction_id, reason)
    outbox.mark_rejected(record.transaction_id, "synthetic-second-reason")
    assert [event.transaction_id for event in outbox.get_pending(10)] == [other.transaction_id]
    with closing(connect(path)) as conn:
        assert (
            conn.execute(
                "SELECT rejection_reason FROM outbox_events WHERE transaction_id=?",
                (record.transaction_id,),
            ).fetchone()[0]
            == reason
        )
    outbox.mark_synchronized([other.transaction_id])
    assert outbox.get_pending(10) == []


@pytest.mark.parametrize("status", [SyncStatus.SYNCED, SyncStatus.REJECTED, SyncStatus.CONFLICT])
def test_unknown_event_is_not_reported_as_updated(storage, status) -> None:
    _, outbox, path = storage
    before = snapshot(path)
    with pytest.raises(StorageError, match="unknown"):
        mark_status(outbox, str(uuid4()), status)
    assert snapshot(path) == before


@pytest.mark.parametrize("invalid", [None, "", " ", 123])
def test_bad_outbox_id_does_not_update_valid_batch(storage, record, invalid) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with pytest.raises(StorageError):
        outbox.mark_synchronized([record.transaction_id, invalid])
    with pytest.raises(StorageError):
        outbox.mark_conflict(invalid)
    with pytest.raises(StorageError):
        outbox.mark_rejected(invalid, "SYNTHETIC")
    assert snapshot(path) == before


@pytest.mark.parametrize("invalid", [None, "", " ", 123])
def test_bad_rejection_reason_does_not_quarantine(storage, record, invalid) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with pytest.raises(StorageError, match="reason"):
        outbox.mark_rejected(record.transaction_id, invalid)
    assert snapshot(path) == before


@pytest.mark.parametrize("failure", ["update", "commit"])
def test_status_failure_rolls_back_entire_batch(storage, record, failure) -> None:
    repo, outbox, path = storage
    other = replace(record, transaction_id=str(uuid4()))
    repo.save_record_with_outbox(record)
    repo.save_record_with_outbox(other)
    before = snapshot(path)
    with closing(connect(path)) as conn, conn:
        if failure == "update":
            conn.execute(
                "CREATE TRIGGER synthetic_status_failure BEFORE UPDATE ON outbox_events "
                f"WHEN OLD.transaction_id='{other.transaction_id}' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic update failure'); END"
            )
        else:
            conn.execute("CREATE TABLE synthetic_parent (id INTEGER PRIMARY KEY)")
            conn.execute(
                """CREATE TABLE synthetic_child (id INTEGER REFERENCES synthetic_parent(id)
                DEFERRABLE INITIALLY DEFERRED)"""
            )
            conn.execute(
                """CREATE TRIGGER synthetic_status_failure AFTER UPDATE ON outbox_events
                BEGIN INSERT INTO synthetic_child VALUES (1); END"""
            )
    with pytest.raises(StorageError):
        outbox.mark_synchronized([record.transaction_id, other.transaction_id])
    assert snapshot(path) == before
    with closing(connect(path)) as conn, conn:
        conn.execute("DROP TRIGGER synthetic_status_failure")
    outbox.mark_synchronized([record.transaction_id, other.transaction_id])
    assert outbox.get_pending(10) == []


def test_legacy_outbox_upgrade_preserves_pending_and_identity(storage, record) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    with closing(connect(path)) as conn, conn:
        conn.execute("ALTER TABLE outbox_events DROP COLUMN rejection_reason")
    before = snapshot(path)
    # Status write upgrades a database created by the preceding implementation.
    outbox.mark_rejected(record.transaction_id, "SYNTHETIC_LEGACY")
    after = snapshot(path)
    assert after[0] == before[0]
    assert after[1][0][:1] == before[1][0][:1]
    assert after[1][0][2] == before[1][0][2]
    assert after[1][0][3] == "SYNTHETIC_LEGACY"


def test_status_lock_failure_preserves_pending(storage, record) -> None:
    repo, outbox, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with closing(connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(StorageError):
                outbox.mark_conflict(record.transaction_id)
        finally:
            conn.rollback()
    assert snapshot(path) == before
    outbox.mark_conflict(record.transaction_id)
    assert outbox.get_pending(10) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sequence": 0},
        {"source_sequence": -1},
        {"source_sequence": True},
        {"source_sequence": 1.5},
        {"source_sequence": None},
        {"source_sequence": 2**63},
        {"policy_version": ""},
        {"policy_version": " "},
        {"policy_version": None},
        {"controller_ack": None},
        {"controller_ack": "ACKNOWLEDGED"},
        {"controller_ack": GateAck.REJECTED},
        {"controller_ack": GateAck.TIMEOUT},
        {"controller_ack": GateAck.UNAVAILABLE},
    ],
)
def test_invalid_a1_metadata_never_creates_event(storage, record, changes) -> None:
    repo, _, path = storage
    with pytest.raises((StorageError, ValueError)):
        repo.save_record_with_outbox(replace(record, **changes))
    assert snapshot(path) == ([], [])


@pytest.mark.parametrize(
    "changes", [{"source_sequence": 2}, {"policy_version": "synthetic-policy-v2"}]
)
def test_resend_cannot_replace_original_a1_metadata(storage, record, changes) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    before = snapshot(path)
    with pytest.raises(StorageError, match="conflicting"):
        repo.save_record_with_outbox(replace(record, **changes))
    assert snapshot(path) == before


def test_pending_reads_preserve_actual_a1_metadata_across_reopen(storage, record) -> None:
    repo, _, path = storage
    event = replace(record, source_sequence=87, policy_version="synthetic-policy-v9")
    repo.save_record_with_outbox(event)
    SqliteAttendanceRepository(path)
    recovered = SqliteOutboxRepository(path).get_pending(1)[0]
    assert recovered.source_sequence == 87
    assert recovered.policy_version == "synthetic-policy-v9"
    assert recovered.controller_ack is GateAck.ACKNOWLEDGED
    assert recovered.confirmation_evidence is ConfirmationEvidence.PASSAGE_CONFIRMED
    repo.save_record_with_outbox(recovered)
    assert SqliteOutboxRepository(path).get_pending(1) == [recovered]


def test_legacy_attendance_is_preserved_without_invented_metadata(storage, record) -> None:
    repo, _, path = storage
    repo.save_record_with_outbox(record)
    with closing(connect(path)) as conn, conn:
        for column in ("controller_ack", "policy_version", "source_sequence"):
            conn.execute(f"ALTER TABLE attendance_records DROP COLUMN {column}")
    before = snapshot(path)
    SqliteAttendanceRepository(path)
    after = snapshot(path)
    assert after[0][0][:10] == before[0][0]
    assert after[0][0][10:] == (None, None, None)
    assert after[1] == before[1]
    with pytest.raises(StorageError, match="metadata"):
        SqliteOutboxRepository(path).get_pending(10)
    assert snapshot(path) == after


def test_next_sequence_allocates_monotonic_integers(storage, record) -> None:
    repo, _, path = storage
    # Empty DB starts at 1
    assert repo.next_sequence() == 1
    repo.save_record_with_outbox(record)  # record has source_sequence=1
    assert repo.next_sequence() == 2
    # Save a second attempt to satisfy FK constraint
    repo.save_attempt(
        AccessAttempt(
            "att-2",
            "synthetic-station",
            "synthetic-gate",
            Direction.ENTRY,
            datetime(2026, 11, 9, tzinfo=UTC),
            status=AttemptStatus.PASSAGE_CONFIRMED,
            subject_id="synthetic-subject",
        )
    )
    repo.save_record_with_outbox(
        replace(record, transaction_id=str(uuid4()), access_attempt_id="att-2", source_sequence=87)
    )
    assert repo.next_sequence() == 88
    # Reopened repo also reads from database
    reopened = SqliteAttendanceRepository(path)
    assert reopened.next_sequence() == 88
