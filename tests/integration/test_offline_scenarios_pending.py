"""Offline gate-operation integration test. Owner: Bui Doan Minh Nhat."""

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
from tmc_access.domain.errors import SyncError
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


class _StaticSnapshotProvider:
    def __init__(self, snapshot: PolicySnapshot) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> PolicySnapshot:
        return self._snapshot


def _make_signed_qr(
    key: Ed25519PrivateKey,
    *,
    subject_id: str,
    station_id: str,
    now: datetime,
    issuer: str = "tmc-hub",
    kid: str = "key-v1",
    valid_seconds: int = 60,
) -> str:
    iat = int(now.timestamp())
    claims = {
        "iss": issuer,
        "sub": subject_id,
        "jti": str(uuid4()),
        "kid": kid,
        "aud": station_id,
        "iat": iat,
        "exp": iat + valid_seconds,
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode("ascii")).rstrip(b"=")
    sig = base64.urlsafe_b64encode(key.sign(body)).rstrip(b"=")
    return (body + b"." + sig).decode("ascii")


def test_network_disconnection_keeps_gate_working(tmp_path) -> None:
    """Scenario 7: Hub disconnection does not block local QR, policy, gate, or persistence."""
    db_path = tmp_path / "edge.db"
    hub_db_path = tmp_path / "hub.db"
    now = datetime(2026, 11, 14, 8, 0, 0, tzinfo=UTC)

    # 1. Simulated Hub is offline
    receiver = SimulatedHubReceiver(hub_db_path)
    sync_client = SimulatedSyncClient(receiver)
    sync_client.connected = False
    assert sync_client.connected is False

    # 2. Local Ed25519 QR verification at the Edge
    hub_key = Ed25519PrivateKey.generate()
    validator = PublicKeyQrValidator(
        {"key-v1": hub_key.public_key()},
        ReplayGuardStore(),
        trusted_issuer="tmc-hub",
    )

    # 3. Local policy snapshot allows access
    snapshot = PolicySnapshot(
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
        _StaticSnapshotProvider(snapshot),
        fresh_for=timedelta(minutes=5),
        max_stale_for=timedelta(hours=2),
    )

    # 4. Mock turnstile acknowledges unlock and confirms passage
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    attendance_repo = SqliteAttendanceRepository(db_path)
    outbox_repo = SqliteOutboxRepository(db_path)
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

    qr_payload = _make_signed_qr(
        hub_key,
        subject_id="emp-001",
        station_id="station-north",
        now=now,
    )
    attempt = coordinator.handle_scan(
        ScanInput(
            request_id="req-offline-001",
            station_id="station-north",
            gate_id="gate-1",
            direction=Direction.ENTRY,
            received_at=now,
            payload=qr_payload,
        )
    )
    assert attempt.status is AttemptStatus.PASSAGE_CONFIRMED
    assert attempt.subject_id == "emp-001"

    # 5 & 6. AttendanceRecord is persisted in SQLite and OutboxEvent remains PENDING
    with closing(sqlite3.connect(db_path)) as conn:
        rec_row = conn.execute(
            "SELECT transaction_id, access_attempt_id, employee_id, "
            "confirmation_evidence, controller_ack FROM attendance_records"
        ).fetchone()
        assert rec_row is not None
        transaction_id = rec_row[0]
        assert rec_row[1] == "req-offline-001"
        assert rec_row[2] == "emp-001"
        assert rec_row[3] == ConfirmationEvidence.PASSAGE_CONFIRMED.value
        assert rec_row[4] == GateAck.ACKNOWLEDGED.value

        outbox_row = conn.execute(
            "SELECT transaction_id, sync_status FROM outbox_events"
        ).fetchone()
        assert outbox_row == (transaction_id, SyncStatus.PENDING.value)

    # 7. Sync fails while offline and no Hub delivery occurs; OutboxEvent stays PENDING
    sync_service = SyncService(outbox_repo, sync_client)
    with pytest.raises(SyncError):
        sync_service.sync_once()

    assert receiver.event_count == 0
    pending = outbox_repo.get_pending(10)
    assert len(pending) == 1
    assert pending[0].transaction_id == transaction_id
    assert pending[0].sync_status is SyncStatus.PENDING
