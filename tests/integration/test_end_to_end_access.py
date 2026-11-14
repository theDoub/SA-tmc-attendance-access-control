"""End-to-end integration test: Full access lifecycle.

Covers the complete pipeline across all 4 team members' components:
QR validation (Hiếu)
  → Policy evaluation (Kim)
  → Gate simulation (Nhật)
  → Passage confirmation (Nhật/Kim)
  → AttendanceRecord creation (Kim)
  → SQLite WAL persistence (Nhật)
  → Transactional Outbox (Nhật)
  → Store-and-Forward synchronization (Nhật).
"""

import base64
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.application.synchronization.sync_service import SyncService
from tmc_access.domain.models import (
    AccessGrant,
    AttemptStatus,
    ConfirmationEvidence,
    Direction,
    GateAck,
    PolicySnapshot,
    ScanInput,
    SubjectPolicy,
    SyncStatus,
)
from tmc_access.domain.policies import AccessPolicyEvaluator
from tmc_access.infrastructure.persistence.sqlite import (
    SqliteAttendanceRepository,
    SqliteOutboxRepository,
)
from tmc_access.infrastructure.qr.public_key_validator import PublicKeyQrValidator
from tmc_access.infrastructure.qr.replay_guard import ReplayGuardStore
from tmc_access.infrastructure.synchronization.simulation import (
    SimulatedHubReceiver,
    SimulatedSyncClient,
)
from tmc_access.infrastructure.turnstile.mock_turnstile import (
    MockScenario,
    MockTurnstileAdapter,
)

pytestmark = pytest.mark.integration


class StaticSnapshotProvider:
    def __init__(self, snapshot: PolicySnapshot) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> PolicySnapshot:
        return self._snapshot


def make_signed_qr(
    key: Ed25519PrivateKey,
    *,
    subject_id: str,
    station_id: str,
    issuer: str = "tmc-hub",
    kid: str = "key-v1",
    now: datetime,
    valid_seconds: int = 60,
) -> str:
    iat = int(now.timestamp())
    exp = iat + valid_seconds
    claims = {
        "iss": issuer,
        "sub": subject_id,
        "jti": str(uuid4()),
        "kid": kid,
        "aud": station_id,
        "iat": iat,
        "exp": exp,
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode("ascii")).rstrip(b"=")
    sig = base64.urlsafe_b64encode(key.sign(body)).rstrip(b"=")
    return (body + b"." + sig).decode("ascii")


def test_full_access_lifecycle_end_to_end(tmp_path) -> None:
    db_path = tmp_path / "edge.db"
    hub_db_path = tmp_path / "hub.db"
    now = datetime(2026, 11, 14, 8, 0, 0, tzinfo=UTC)

    # 1. Setup Cryptographic verification (Hiếu)
    hub_key = Ed25519PrivateKey.generate()
    replay_guard = ReplayGuardStore()
    validator = PublicKeyQrValidator(
        {"key-v1": hub_key.public_key()},
        replay_guard,
        trusted_issuer="tmc-hub",
    )

    # 2. Setup Access Policy Engine (Kim)
    policy_snapshot = PolicySnapshot(
        version="policy-v2026.1",
        refreshed_at=now - timedelta(minutes=1),
        subjects=(
            SubjectPolicy(
                subject_id="emp-001",
                active=True,
                grants=frozenset({AccessGrant(gate_id="gate-1", direction=Direction.ENTRY)}),
            ),
        ),
    )
    policy_evaluator = AccessPolicyEvaluator(
        StaticSnapshotProvider(policy_snapshot),
        fresh_for=timedelta(minutes=5),
        max_stale_for=timedelta(hours=2),
    )

    # 3. Setup Hardware Turnstile Adapter (Nhật)
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())

    # 4. Setup SQLite WAL Persistence & Outbox (Nhật)
    attendance_repo = SqliteAttendanceRepository(db_path)
    outbox_repo = SqliteOutboxRepository(db_path)

    # 5. Assemble Access Coordinator (Kim / Wiring)
    coordinator = AccessCoordinator(
        validator=validator,
        policy_engine=policy_evaluator,
        gate=gate,
        attendance_repository=attendance_repo,
        factory_id="factory-binhduong",
        turnstile_timeout_ms=800,
        passage_window_seconds=15,
        clock=lambda: now,
    )

    # 6. Issue dynamic signed QR for emp-001
    qr_payload = make_signed_qr(
        hub_key,
        subject_id="emp-001",
        station_id="station-north",
        now=now,
    )
    scan = ScanInput(
        request_id="req-scan-001",
        station_id="station-north",
        gate_id="gate-1",
        direction=Direction.ENTRY,
        received_at=now,
        payload=qr_payload,
    )

    # 7. Execute Scan: QR -> Policy -> Attempt -> Unlock -> Passage -> Attendance + Outbox
    attempt = coordinator.handle_scan(scan)

    # Assertions on in-memory outcome
    assert attempt.status == AttemptStatus.PASSAGE_CONFIRMED
    assert attempt.subject_id == "emp-001"
    assert attempt.policy_version == "policy-v2026.1"
    assert attempt.stale_cache_used is False

    # 8. Assertions on local SQLite database
    with closing(sqlite3.connect(db_path)) as conn:
        # Check attempts table
        att_row = conn.execute(
            "SELECT access_attempt_id, status, subject_id "
            "FROM access_attempts WHERE access_attempt_id=?",
            ("req-scan-001",),
        ).fetchone()
        assert att_row == ("req-scan-001", "PASSAGE_CONFIRMED", "emp-001")

        # Check attendance_records table
        rec_row = conn.execute(
            "SELECT access_attempt_id, employee_id, factory_id, confirmation_evidence, "
            "source_sequence, policy_version, controller_ack FROM attendance_records"
        ).fetchone()
        assert rec_row[0] == "req-scan-001"
        assert rec_row[1] == "emp-001"
        assert rec_row[2] == "factory-binhduong"
        assert rec_row[3] == ConfirmationEvidence.PASSAGE_CONFIRMED.value
        assert rec_row[4] == 1  # Allocated source sequence
        assert rec_row[5] == "policy-v2026.1"
        assert rec_row[6] == GateAck.ACKNOWLEDGED.value

        # Check outbox_events table
        outbox_row = conn.execute("SELECT sync_status FROM outbox_events").fetchone()
        assert outbox_row == (SyncStatus.PENDING.value,)

    # 9. Verify Outbox Sync to Hub Simulation
    pending = outbox_repo.get_pending(10)
    assert len(pending) == 1
    assert pending[0].employee_id == "emp-001"
    assert pending[0].source_sequence == 1
    assert pending[0].controller_ack is GateAck.ACKNOWLEDGED

    receiver = SimulatedHubReceiver(hub_db_path)
    client = SimulatedSyncClient(receiver)
    sync_service = SyncService(outbox_repo, client)

    # Push batch
    sync_service.sync_once()

    # Outbox status must be updated to SYNCED
    assert outbox_repo.get_pending(10) == []
    with closing(sqlite3.connect(db_path)) as conn:
        synced_status = conn.execute("SELECT sync_status FROM outbox_events").fetchone()[0]
        assert synced_status == SyncStatus.SYNCED.value
    assert receiver.event_count == 1

    # Idempotent resend: sending again causes no error and duplicates no record
    sync_service.sync_once()
    assert receiver.event_count == 1

    # 10. Replay attack verification: presenting the exact same QR payload again
    replay_scan = ScanInput(
        request_id="req-scan-002",
        station_id="station-north",
        gate_id="gate-1",
        direction=Direction.ENTRY,
        received_at=now + timedelta(seconds=5),
        payload=qr_payload,
    )
    replay_attempt = coordinator.handle_scan(replay_scan)
    assert replay_attempt.status == AttemptStatus.DENIED
    assert replay_attempt.reason_code == "QR_REPLAYED"
    # No gate unlock, no new attendance record
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT count(*) FROM attendance_records").fetchone()[0] == 1
