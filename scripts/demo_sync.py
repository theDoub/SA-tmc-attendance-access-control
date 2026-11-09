"""Component demo with synthetic records and a virtual clock; no QR/access-core claim.

Run: .venv/Scripts/python.exe scripts/demo_sync.py
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from tmc_access.config.container import build_container
from tmc_access.config.settings import Settings
from tmc_access.domain.models import (
    AccessAttempt,
    AttemptStatus,
    AttendanceRecord,
    ConfirmationEvidence,
    Direction,
    GateAck,
)


def demo(directory: Path) -> None:
    now = [0.0]
    runtime = build_container(
        Settings(
            _env_file=None,
            edge_id="synthetic-edge",
            station_id="synthetic-station",
            factory_id="synthetic-factory",
            sqlite_path=directory / "edge.db",
            sync_mode="simulation",
            turnstile_mode="mock",
            turnstile_mock_scenario="acked_with_passage",
        ),
        clock=lambda: now[0],
        random_uniform=lambda low, high: high,
    )
    client, receiver = runtime.simulation_client, runtime.simulation_receiver
    assert client is not None and receiver is not None
    repo, outbox, worker = (
        runtime.attendance_repository,
        runtime.outbox_repository,
        runtime.sync_worker,
    )

    def event(sequence: int) -> AttendanceRecord:
        attempt_id = str(uuid4())
        timestamp = datetime.now(UTC)
        # Explicit synthetic evidence: this script does not execute QR/policy/coordinator.
        repo.save_attempt(
            AccessAttempt(
                attempt_id,
                "synthetic-station",
                "synthetic-gate",
                Direction.ENTRY,
                timestamp,
                status=AttemptStatus.PASSAGE_CONFIRMED,
                subject_id="synthetic-subject",
            )
        )
        record = AttendanceRecord(
            str(uuid4()),
            attempt_id,
            "synthetic-subject",
            "synthetic-factory",
            "synthetic-station",
            "synthetic-gate",
            Direction.ENTRY,
            timestamp,
            ConfirmationEvidence.PASSAGE_CONFIRMED,
            sequence,
            "synthetic-policy-v1",
            GateAck.ACKNOWLEDGED,
        )
        repo.save_record_with_outbox(record)
        return record

    def tick_due() -> None:
        now[0] = worker.next_attempt_at
        worker.tick()

    client.connected = False
    event(1)
    tick_due()
    assert len(outbox.get_pending(100)) == 1 and receiver.event_count == 0
    print("1. Offline: 1 PENDING; first retry scheduled after 5 virtual seconds.")
    client.connected = True
    tick_due()
    assert outbox.get_pending(100) == [] and receiver.event_count == 1
    print("2. Reconnected: accepted ACK applied; 1 event stored at receiver.")
    event(2)
    client.lose_ack_once = True
    tick_due()
    assert len(outbox.get_pending(100)) == 1 and receiver.event_count == 2
    print("3. ACK lost after commit: original event remains PENDING.")
    client.connected = True
    tick_due()
    assert outbox.get_pending(100) == [] and receiver.event_count == 2
    print("4. Retry: same ID/content accepted; receiver still has 2 events.")
    conflict = event(3)
    receiver.ingest([replace(conflict, employee_id="synthetic-other")])
    rejected = event(4)
    receiver.reject_event(rejected.transaction_id, "SYNTHETIC_INVALID_EVENT")
    tick_due()
    assert outbox.get_pending(100) == [] and receiver.event_count == 3
    print("5. Conflicting ID and permanent rejection retained outside pending.")
    print("Demo completed. Virtual time; no hardware, real Hub or HR/Payroll.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="Keep demo DBs in a NEW directory")
    args = parser.parse_args()
    if args.directory is None:
        with TemporaryDirectory(prefix="tmc-sync-simulation-") as directory:
            demo(Path(directory))
    else:
        args.directory.mkdir(parents=True, exist_ok=False)
        demo(args.directory)


if __name__ == "__main__":
    main()
