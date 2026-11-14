"""Real Edge SQLite + persisted simulated receiver; time/network are controlled."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

import pytest

from tmc_access.application.synchronization.sync_service import SyncService
from tmc_access.config.container import build_container
from tmc_access.domain.errors import StorageError, SyncError
from tmc_access.domain.models import (
    AccessAttempt,
    AttemptStatus,
    AttendanceRecord,
    ConfirmationEvidence,
    Direction,
    GateAck,
    PassageStatus,
    RejectedEvent,
    SyncResult,
    SyncStatus,
)
from tmc_access.infrastructure.persistence import sqlite as edge_storage
from tmc_access.infrastructure.persistence.sqlite import connect

pytestmark = pytest.mark.integration


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def simulation(settings):
    clock = Clock()
    settings = settings.model_copy(update={"sync_mode": "simulation"})
    return build_container(settings, clock=clock, random_uniform=lambda low, high: high), clock


def enqueue(runtime, sequence=1):
    event_id, attempt_id = str(uuid4()), str(uuid4())
    now = datetime(2026, 11, 9, tzinfo=UTC)
    attempt = AccessAttempt(
        attempt_id,
        "synthetic-station",
        "synthetic-gate",
        Direction.ENTRY,
        now,
        status=AttemptStatus.ALLOWED_PERSISTED,
        subject_id="synthetic-subject",
    )
    runtime.attendance_repository.save_attempt(attempt)
    ack = runtime.gate.unlock(attempt_id, attempt.gate_id, attempt.direction, 800)
    assert ack.ack is GateAck.ACKNOWLEDGED
    assert runtime.gate.query_passage(attempt_id, 15) is PassageStatus.CONFIRMED
    runtime.attendance_repository.update_attempt(
        replace(attempt, status=AttemptStatus.PASSAGE_CONFIRMED)
    )
    event = AttendanceRecord(
        event_id,
        attempt_id,
        "synthetic-subject",
        "synthetic-factory",
        attempt.station_id,
        attempt.gate_id,
        attempt.direction,
        now,
        ConfirmationEvidence.PASSAGE_CONFIRMED,
        sequence,
        "synthetic-policy-v1",
        ack.ack,
    )
    runtime.attendance_repository.save_record_with_outbox(event)
    return event


def states(runtime):
    with closing(sqlite3.connect(runtime.settings.sqlite_path)) as conn:
        return dict(conn.execute("SELECT transaction_id, sync_status FROM outbox_events"))


def test_offline_local_processing_then_reconnect_syncs_same_event(simulation) -> None:
    runtime, clock = simulation
    runtime.simulation_client.connected = False
    event = enqueue(runtime)  # Uses local mock + real repositories, not the pending coordinator.
    assert runtime.sync_worker.tick()
    assert states(runtime)[event.transaction_id] == "PENDING"
    assert runtime.simulation_receiver.event_count == 0
    assert runtime.sync_worker.next_attempt_at == 5
    assert not runtime.sync_worker.tick()
    runtime.simulation_client.connected = True
    clock.now = runtime.sync_worker.next_attempt_at
    assert runtime.sync_worker.tick()
    assert states(runtime)[event.transaction_id] == "SYNCED"
    assert runtime.simulation_receiver.event_count == 1
    assert runtime.simulation_client.sent_batches == [(event,), (event,)]
    assert runtime.sync_worker.failures == 0


def test_disconnect_mid_batch_and_restart_retries_original_pending(simulation) -> None:
    runtime, _ = simulation
    events = [enqueue(runtime, i) for i in (1, 2)]
    runtime.simulation_client.disconnect_after_events = 1
    runtime.sync_worker.tick()
    assert runtime.simulation_receiver.event_count == 1
    assert set(states(runtime).values()) == {"PENDING"}
    restarted = build_container(runtime.settings)
    restarted.sync_worker.tick()
    assert restarted.simulation_receiver.event_count == 2
    assert set(states(restarted).values()) == {"SYNCED"}
    assert set(restarted.simulation_client.sent_batches[0]) == set(events)


def test_ack_lost_after_commit_resends_without_duplicate_even_after_restart(simulation) -> None:
    runtime, _ = simulation
    event = enqueue(runtime)
    runtime.simulation_client.lose_ack_once = True
    runtime.sync_worker.tick()
    assert runtime.simulation_receiver.event_count == 1
    assert states(runtime)[event.transaction_id] == "PENDING"
    restarted = build_container(runtime.settings)
    restarted.sync_service.sync_once()
    assert restarted.simulation_receiver.event_count == 1
    assert states(restarted)[event.transaction_id] == "SYNCED"
    assert restarted.simulation_client.sent_batches == [(event,)]


def test_mixed_accepted_rejected_conflict_and_transient_results(simulation) -> None:
    runtime, _ = simulation
    accepted, rejected, conflict, transient = [enqueue(runtime, i) for i in range(1, 5)]
    runtime.simulation_receiver.ingest([replace(conflict, employee_id="synthetic-other")])
    runtime.simulation_receiver.reject_event(rejected.transaction_id, "SYNTHETIC_INVALID")
    runtime.simulation_receiver.reject_event(transient.transaction_id, "SYNTHETIC_BUSY", False)
    with pytest.raises(SyncError):
        runtime.sync_service.sync_once()
    assert states(runtime) == {
        accepted.transaction_id: "SYNCED",
        rejected.transaction_id: "REJECTED",
        conflict.transaction_id: "CONFLICT",
        transient.transaction_id: "PENDING",
    }
    assert runtime.simulation_receiver.event_count == 2
    runtime.simulation_receiver.clear_rejection(transient.transaction_id)
    runtime.sync_service.sync_once()
    assert states(runtime)[transient.transaction_id] == "SYNCED"
    assert runtime.outbox_repository.get_pending(100) == []


def test_duplicate_ingestion_ignores_delivery_status_but_compares_metadata(simulation) -> None:
    runtime, _ = simulation
    event = enqueue(runtime)
    receiver = runtime.simulation_receiver
    assert receiver.ingest([event]).accepted_ids == (event.transaction_id,)
    assert receiver.ingest([replace(event, sync_status=SyncStatus.SYNCED)]).accepted_ids == (
        event.transaction_id,
    )
    result = receiver.ingest([replace(event, policy_version="synthetic-policy-v2")])
    assert result.conflict_ids == (event.transaction_id,)
    assert result.accepted_ids == ()
    assert receiver.event_count == 1


def test_backoff_caps_and_resets_using_configured_jitter(simulation) -> None:
    runtime, clock = simulation
    enqueue(runtime)
    runtime.simulation_client.connected = False
    for delay in (5, 10, 20, 40, 60, 60):
        start = clock.now
        assert runtime.sync_worker.tick()
        assert runtime.sync_worker.next_attempt_at - start == delay
        clock.now = runtime.sync_worker.next_attempt_at - 0.001
        assert not runtime.sync_worker.tick()
        clock.now += 0.001
    runtime.simulation_client.connected = True
    runtime.sync_worker.tick()
    assert runtime.sync_worker.failures == 0
    assert runtime.sync_worker.last_error is None
    clock.now = runtime.sync_worker.next_attempt_at
    enqueue(runtime, 2)
    runtime.simulation_client.connected = False
    runtime.sync_worker.tick()
    assert runtime.sync_worker.next_attempt_at - clock.now == 5


def test_custom_backoff_and_minimum_jitter_flow_from_settings(simulation) -> None:
    runtime, clock = simulation
    settings = runtime.settings.model_copy(update={"sync_backoff_delays_seconds": (2, 3)})
    configured = build_container(settings, clock=clock, random_uniform=lambda low, high: low)
    enqueue(configured)
    configured.simulation_client.connected = False
    configured.sync_worker.tick()
    assert configured.sync_worker.next_attempt_at == pytest.approx(1.6)
    clock.now = configured.sync_worker.next_attempt_at
    configured.sync_worker.tick()
    assert configured.sync_worker.next_attempt_at - clock.now == pytest.approx(2.4)


@pytest.mark.parametrize("invalid", ["unknown", "duplicate", "overlap", "reason", "type"])
def test_invalid_ack_does_not_change_any_local_state(simulation, invalid) -> None:
    runtime, _ = simulation
    event = enqueue(runtime)
    replies = {
        "unknown": SyncResult((str(uuid4()),)),
        "duplicate": SyncResult((event.transaction_id, event.transaction_id)),
        "overlap": SyncResult((event.transaction_id,), conflict_ids=(event.transaction_id,)),
        "reason": SyncResult(rejected=(RejectedEvent(event.transaction_id, "", True),)),
        "type": None,
    }

    class BadClient:
        def push_events(self, batch):
            return replies[invalid]

    service = SyncService(runtime.outbox_repository, BadClient())
    with pytest.raises(SyncError):
        service.sync_once()
    assert states(runtime) == {event.transaction_id: "PENDING"}


def test_partial_ack_only_marks_accepted_subset(simulation) -> None:
    runtime, _ = simulation
    first, second = enqueue(runtime, 1), enqueue(runtime, 2)

    class PartialClient:
        def push_events(self, batch):
            return SyncResult((first.transaction_id,))

    with pytest.raises(SyncError):
        SyncService(runtime.outbox_repository, PartialClient()).sync_once()
    assert states(runtime) == {first.transaction_id: "SYNCED", second.transaction_id: "PENDING"}


def test_local_ack_write_failure_can_retry_safely(simulation) -> None:
    runtime, clock = simulation
    event = enqueue(runtime)
    with closing(connect(runtime.settings.sqlite_path)) as conn, conn:
        conn.execute(
            """CREATE TRIGGER synthetic_ack_failure BEFORE UPDATE ON outbox_events
            BEGIN SELECT RAISE(ABORT, 'synthetic ack storage error'); END"""
        )
    runtime.sync_worker.tick()
    assert runtime.sync_worker.last_error == "StorageError"
    assert runtime.simulation_receiver.event_count == 1
    assert states(runtime)[event.transaction_id] == "PENDING"
    with closing(connect(runtime.settings.sqlite_path)) as conn, conn:
        conn.execute("DROP TRIGGER synthetic_ack_failure")
    clock.now = runtime.sync_worker.next_attempt_at
    runtime.sync_worker.tick()
    assert runtime.simulation_receiver.event_count == 1
    assert states(runtime)[event.transaction_id] == "SYNCED"


def test_receiver_insert_failure_never_acknowledges_success(simulation) -> None:
    runtime, _ = simulation
    event = enqueue(runtime)
    receiver_path = runtime.settings.sqlite_path.with_name("simulated-hub.db")
    with closing(sqlite3.connect(receiver_path)) as conn, conn:
        conn.execute(
            """CREATE TRIGGER synthetic_ingestion_failure BEFORE INSERT ON simulated_events
            BEGIN SELECT RAISE(ABORT, 'synthetic receiver failure'); END"""
        )
    with pytest.raises(SyncError):
        runtime.sync_service.sync_once()
    assert states(runtime)[event.transaction_id] == "PENDING"
    assert runtime.simulation_receiver.event_count == 0


def test_batch_size_and_empty_queue_do_not_contact_network(simulation) -> None:
    runtime, _ = simulation
    runtime.sync_service.sync_once()
    assert runtime.simulation_client.sent_batches == []
    enqueue(runtime, 1)
    enqueue(runtime, 2)
    SyncService(runtime.outbox_repository, runtime.simulation_client, batch_size=1).sync_once()
    assert len(runtime.outbox_repository.get_pending(100)) == 1
    assert runtime.simulation_receiver.event_count == 1


def test_background_loop_delivers_and_stops_cleanly(simulation, monkeypatch) -> None:
    runtime, _ = simulation
    event = enqueue(runtime)
    stop = Event()
    ingest = runtime.simulation_receiver.ingest

    def receive_and_stop(batch):
        result = ingest(batch)
        stop.set()
        return result

    monkeypatch.setattr(runtime.simulation_receiver, "ingest", receive_and_stop)
    thread = Thread(target=runtime.sync_worker.run, args=(stop,))
    thread.start()
    try:
        assert stop.wait(3)
    finally:
        stop.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert states(runtime)[event.transaction_id] == "SYNCED"


def test_receiver_batch_rollback_does_not_ack_partially_written_events(simulation) -> None:
    runtime, _ = simulation
    first, second = enqueue(runtime, 1), enqueue(runtime, 2)
    receiver_path = runtime.settings.sqlite_path.with_name("simulated-hub.db")
    with closing(sqlite3.connect(receiver_path)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER synthetic_second_failure BEFORE INSERT ON simulated_events "
            f"WHEN NEW.transaction_id='{second.transaction_id}' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic second event failure'); END"
        )
    with pytest.raises(SyncError):
        runtime.simulation_receiver.ingest([first, second])
    assert runtime.simulation_receiver.event_count == 0
    assert set(states(runtime).values()) == {"PENDING"}


@pytest.mark.parametrize("storage_failure", [False, True])
def test_network_drops_inside_local_attendance_transaction(
    simulation, monkeypatch, storage_failure
) -> None:
    runtime, clock = simulation
    original_connect = edge_storage.connect
    cuts = []

    def cut_network():
        runtime.simulation_client.connected = False
        cuts.append(True)
        return 0

    def connect_with_fault(path):
        conn = original_connect(path)
        conn.create_function("synthetic_disconnect", 0, cut_network)
        return conn

    with closing(connect(runtime.settings.sqlite_path)) as conn, conn:
        failure = "SELECT RAISE(ABORT, 'synthetic storage failure');" if storage_failure else ""
        conn.execute(
            "CREATE TRIGGER synthetic_network_cut AFTER INSERT ON attendance_records "
            f"BEGIN SELECT synthetic_disconnect(); {failure} END"
        )
    monkeypatch.setattr(edge_storage, "connect", connect_with_fault)
    if storage_failure:
        with pytest.raises(StorageError):
            enqueue(runtime)
        assert states(runtime) == {}
        with closing(connect(runtime.settings.sqlite_path)) as conn:
            assert conn.execute("SELECT count(*) FROM attendance_records").fetchone()[0] == 0
    else:
        event = enqueue(runtime)
        assert states(runtime) == {event.transaction_id: "PENDING"}
        runtime.sync_worker.tick()
        assert runtime.sync_worker.last_error == "SyncError"
        assert runtime.simulation_receiver.event_count == 0
        runtime.simulation_client.connected = True
        clock.now = runtime.sync_worker.next_attempt_at
        runtime.sync_worker.tick()
        assert states(runtime) == {event.transaction_id: "SYNCED"}
        assert runtime.simulation_receiver.event_count == 1
    assert cuts == [True]
    assert runtime.simulation_client.connected is (not storage_failure)


def test_receiver_commit_failure_keeps_edge_pending_and_returns_no_ack(
    simulation, monkeypatch
) -> None:
    runtime, clock = simulation
    event = enqueue(runtime)
    receiver = runtime.simulation_receiver
    original_connect = receiver._connect

    def enforce_foreign_keys():
        conn = original_connect()
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(receiver, "_connect", enforce_foreign_keys)
    with closing(receiver._connect()) as conn, conn:
        conn.execute("CREATE TABLE synthetic_parent (id INTEGER PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE synthetic_child (id INTEGER REFERENCES synthetic_parent(id)
            DEFERRABLE INITIALLY DEFERRED)"""
        )
        conn.execute(
            """CREATE TRIGGER synthetic_commit_failure AFTER INSERT ON simulated_events
            BEGIN INSERT INTO synthetic_child VALUES (1); END"""
        )
    runtime.sync_worker.tick()
    assert runtime.sync_worker.last_error == "SyncError"
    assert receiver.event_count == 0
    assert states(runtime) == {event.transaction_id: "PENDING"}
    with closing(receiver._connect()) as conn, conn:
        assert conn.execute("SELECT count(*) FROM synthetic_child").fetchone()[0] == 0
        conn.execute("DROP TRIGGER synthetic_commit_failure")
    clock.now = runtime.sync_worker.next_attempt_at
    runtime.sync_worker.tick()
    assert receiver.event_count == 1
    assert states(runtime) == {event.transaction_id: "SYNCED"}
