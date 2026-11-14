"""Demo-only composition root for the TMC Factory Gate Control Center.

Wires the real A2 Edge components (`PublicKeyQrValidator`, `ReplayGuardStore`,
`AccessPolicyEvaluator`, `MockTurnstileAdapter`, `AccessCoordinator`,
`SqliteAttendanceRepository`, `SqliteOutboxRepository`, `SyncService`,
`SyncRetryWorker`, `SimulatedSyncClient`, `SimulatedHubReceiver`) against an
isolated `data/demo/` directory.
"""

import base64
import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.application.synchronization.sync_service import SyncService
from tmc_access.domain.errors import StorageError, SyncError
from tmc_access.domain.models import (
    AccessAttempt,
    AccessGrant,
    AttemptStatus,
    Direction,
    PolicySnapshot,
    ScanInput,
    SubjectPolicy,
)
from tmc_access.domain.policies import AccessPolicyEvaluator, PolicySnapshotProvider
from tmc_access.infrastructure.persistence.sqlite import (
    SqliteAttendanceRepository,
    SqliteOutboxRepository,
    connect,
)
from tmc_access.infrastructure.qr.public_key_validator import PublicKeyQrValidator
from tmc_access.infrastructure.qr.replay_guard import ReplayGuardStore
from tmc_access.infrastructure.synchronization.backoff import BackoffConfig
from tmc_access.infrastructure.synchronization.simulation import (
    SimulatedHubReceiver,
    SimulatedSyncClient,
)
from tmc_access.infrastructure.synchronization.worker import SyncRetryWorker
from tmc_access.infrastructure.turnstile.mock_turnstile import MockScenario, MockTurnstileAdapter
from tmc_access.presentation.demo.router import create_demo_app_from_runtime

DEMO_ISSUER_ID = "tmc-demo-hub"
DEMO_KEY_ID = "demo-hub-ed25519-v1"
DEMO_POLICY_VERSION = "2026.11.14-demo"

FACTORIES: dict[str, dict[str, Any]] = {
    "BINH_DUONG": {
        "name": "Binh Duong Plant (~800 employees)",
        "station_id": "STATION_BD_01",
        "gates": ["GATE_01", "GATE_02"],
    },
    "LONG_AN": {
        "name": "Long An Plant (~600 employees)",
        "station_id": "STATION_LA_01",
        "gates": ["GATE_01", "GATE_02"],
    },
}

DEMO_EMPLOYEES: list[dict[str, Any]] = [
    {
        "employee_id": "emp_001",
        "display_name": "Employee A (Nguyen Van An)",
        "role": "Line Operator",
        "policy_summary": "Active - Authorized at GATE_01 & GATE_02 (ENTRY/EXIT)",
        "active": True,
        "gates": ("GATE_01", "GATE_02"),
    },
    {
        "employee_id": "emp_002",
        "display_name": "Employee B (Tran Thi Binh)",
        "role": "Warehouse Staff",
        "policy_summary": "Active - Authorized at GATE_02 only (Denied at GATE_01)",
        "active": True,
        "gates": ("GATE_02",),
    },
    {
        "employee_id": "emp_003",
        "display_name": "Employee C (Le Hoang Cuong)",
        "role": "Former Contractor",
        "policy_summary": "Inactive - Denied at all gates (SUBJECT_INACTIVE)",
        "active": False,
        "gates": (),
    },
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class _DemoPolicyProvider(PolicySnapshotProvider):
    def get_snapshot(self) -> PolicySnapshot:
        now = datetime.now(UTC)
        subjects = []
        for emp in DEMO_EMPLOYEES:
            grants = frozenset(
                AccessGrant(gate_id=gate, direction=direction)
                for gate in emp["gates"]
                for direction in (Direction.ENTRY, Direction.EXIT)
            )
            subjects.append(
                SubjectPolicy(
                    subject_id=emp["employee_id"],
                    active=emp["active"],
                    grants=grants,
                )
            )
        return PolicySnapshot(
            version=DEMO_POLICY_VERSION,
            refreshed_at=now - timedelta(seconds=1),
            subjects=tuple(subjects),
        )


class DemoCredentialIssuer:
    """Demo-only Ed25519 token issuer (Simulated Central Hub, never Edge)."""

    def __init__(self) -> None:
        self._private_key = Ed25519PrivateKey.generate()
        self.public_key = self._private_key.public_key()

    def issue_signed_qr(
        self, employee_id: str, station_id: str, ttl_seconds: int = 60
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        iat = int(now.timestamp())
        exp = iat + ttl_seconds
        jti = str(uuid4())
        claims = {
            "sub": employee_id,
            "jti": jti,
            "kid": DEMO_KEY_ID,
            "aud": station_id,
            "iss": DEMO_ISSUER_ID,
            "iat": iat,
            "exp": exp,
        }
        body_bytes = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body_b64 = _b64url(body_bytes)
        sig_b64 = _b64url(self._private_key.sign(body_b64.encode("ascii")))
        return {
            "token": f"{body_b64}.{sig_b64}",
            "claims": claims,
            "malformed": False,
        }

    def issue_malformed_qr(self, employee_id: str, station_id: str) -> dict[str, Any]:
        return {
            "token": f"malformed-demo-payload.{_b64url(b'invalid-signature')}",
            "claims": {
                "note": "Intentionally malformed/tampered 2-part token",
                "target_employee": employee_id,
                "target_station": station_id,
            },
            "malformed": True,
        }


class DemoRuntime:
    """Self-contained runtime orchestrating real Edge components for the web demo."""

    def __init__(self, demo_dir: Path | None = None) -> None:
        self._demo_dir = (demo_dir or Path("data/demo")).resolve()
        self._demo_dir.mkdir(parents=True, exist_ok=True)
        self._edge_db_path = self._demo_dir / "edge.db"
        self._hub_db_path = self._demo_dir / "simulated_hub.db"
        self._issuer = DemoCredentialIssuer()
        self._gate_scenario = "acked_with_passage"
        self._worker_now = 0.0
        self._last_sync_message = "Idle"
        self._init_components()

    def _init_components(self) -> None:
        self._replay_guard = ReplayGuardStore()
        self._validator = PublicKeyQrValidator(
            public_keys={DEMO_KEY_ID: self._issuer.public_key},
            replay_guard=self._replay_guard,
            trusted_issuer=DEMO_ISSUER_ID,
        )
        self._policy_engine = AccessPolicyEvaluator(
            _DemoPolicyProvider(),
            fresh_for=timedelta(seconds=300),
            max_stale_for=timedelta(seconds=7200),
        )
        self._attendance_repo = SqliteAttendanceRepository(self._edge_db_path)
        self._outbox_repo = SqliteOutboxRepository(self._edge_db_path)
        self._hub_receiver = SimulatedHubReceiver(self._hub_db_path)
        self._sync_client = SimulatedSyncClient(self._hub_receiver)
        self._sync_service = SyncService(self._outbox_repo, self._sync_client, batch_size=100)
        self._backoff = BackoffConfig(
            delays_seconds=(5.0, 10.0, 20.0, 40.0, 60.0),
            jitter_min=0.8,
            jitter_max=1.0,
        )
        self._worker_now = 0.0
        self._retry_worker = SyncRetryWorker(
            service=self._sync_service,
            backoff=self._backoff,
            clock=lambda: self._worker_now,
        )

    def _build_coordinator(self, factory_id: str, gate_scenario: str) -> AccessCoordinator:
        scenario = MockScenario.by_name(gate_scenario)
        gate = MockTurnstileAdapter(scenario)
        return AccessCoordinator(
            validator=self._validator,
            policy_engine=self._policy_engine,
            gate=gate,
            attendance_repository=self._attendance_repo,
            factory_id=factory_id,
            turnstile_timeout_ms=800,
            passage_window_seconds=15,
        )

    def issue_credential(
        self, employee_id: str, station_id: str, malformed: bool
    ) -> dict[str, Any]:
        known = {e["employee_id"] for e in DEMO_EMPLOYEES}
        if employee_id not in known:
            raise ValueError(f"Unknown demo employee: {employee_id}")
        if malformed:
            return self._issuer.issue_malformed_qr(employee_id, station_id)
        return self._issuer.issue_signed_qr(employee_id, station_id)

    def scan(
        self,
        *,
        factory_id: str,
        station_id: str,
        gate_id: str,
        direction: Direction,
        payload: str,
        gate_scenario: str,
    ) -> dict[str, Any]:
        if factory_id not in FACTORIES:
            raise ValueError(f"Unknown demo factory: {factory_id}")
        MockScenario.by_name(gate_scenario)
        self._gate_scenario = gate_scenario
        coordinator = self._build_coordinator(factory_id, gate_scenario)
        scan_input = ScanInput(
            request_id=f"att_{uuid4().hex[:12]}",
            station_id=station_id,
            gate_id=gate_id,
            direction=direction,
            received_at=datetime.now(UTC),
            payload=payload,
        )
        attempt = coordinator.handle_scan(scan_input)
        attendance_row = self._find_attendance_by_attempt(attempt.access_attempt_id)
        timeline = self._build_timeline(attempt, attendance_row)
        return {
            "attempt": {
                "access_attempt_id": attempt.access_attempt_id,
                "station_id": attempt.station_id,
                "gate_id": attempt.gate_id,
                "direction": attempt.direction.value,
                "received_at": attempt.received_at.isoformat(),
                "status": attempt.status.value,
                "subject_id": attempt.subject_id,
                "reason_code": attempt.reason_code,
                "policy_version": attempt.policy_version,
                "stale_cache_used": attempt.stale_cache_used,
            },
            "attendance": attendance_row,
            "timeline": timeline,
            "state": self.get_state(),
        }

    def set_connectivity(
        self,
        *,
        connected: bool | None = None,
        lose_ack_once: bool | None = None,
        gate_scenario: str | None = None,
    ) -> dict[str, Any]:
        if connected is not None:
            self._sync_client.connected = connected
        if lose_ack_once is not None:
            self._sync_client.lose_ack_once = lose_ack_once
        if gate_scenario is not None:
            MockScenario.by_name(gate_scenario)
            self._gate_scenario = gate_scenario
        return self.get_state()

    def trigger_sync(self, *, mode: str = "sync") -> dict[str, Any]:
        ok = True
        error_detail: str | None = None
        if mode == "retry":
            self._worker_now = max(self._worker_now, self._retry_worker.next_attempt_at)
            self._retry_worker.tick()
            if self._retry_worker.last_error:
                ok = False
                error_detail = self._retry_worker.last_error
                delay = max(0.0, self._retry_worker.next_attempt_at - self._worker_now)
                self._last_sync_message = (
                    f"Retry failed ({error_detail}); next backoff in {delay:.2f}s"
                )
            else:
                self._last_sync_message = "Retry succeeded; pending events synchronized"
        else:
            try:
                self._sync_service.sync_once()
                self._retry_worker.failures = 0
                self._retry_worker.last_error = None
                self._last_sync_message = "Synchronization completed"
            except (SyncError, StorageError) as exc:
                ok = False
                error_detail = str(exc)
                self._last_sync_message = f"Sync failed: {error_detail}"
        return {
            "ok": ok,
            "mode": mode,
            "message": self._last_sync_message,
            "error": error_detail,
            "state": self.get_state(),
        }

    def get_state(self) -> dict[str, Any]:
        counts = {"PENDING": 0, "SYNCED": 0, "REJECTED": 0, "CONFLICT": 0}
        with closing(connect(self._edge_db_path)) as conn:
            for status, count in conn.execute(
                "SELECT sync_status, COUNT(*) FROM outbox_events GROUP BY sync_status"
            ):
                counts[status] = count
            attempt_count = conn.execute("SELECT COUNT(*) FROM access_attempts").fetchone()[0]
            attendance_count = conn.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0]

        next_backoff = max(0.0, self._retry_worker.next_attempt_at - self._worker_now)
        return {
            "factories": FACTORIES,
            "employees": [
                {
                    "employee_id": e["employee_id"],
                    "display_name": e["display_name"],
                    "role": e["role"],
                    "policy_summary": e["policy_summary"],
                    "active": e["active"],
                }
                for e in DEMO_EMPLOYEES
            ],
            "gate_scenario": self._gate_scenario,
            "connectivity": {
                "connected": self._sync_client.connected,
                "lose_ack_once": self._sync_client.lose_ack_once,
            },
            "outbox_counts": counts,
            "attempt_count": attempt_count,
            "attendance_count": attendance_count,
            "hub_event_count": self._hub_receiver.event_count,
            "retry_worker": {
                "failures": self._retry_worker.failures,
                "last_error": self._retry_worker.last_error,
                "next_backoff_seconds": round(next_backoff, 2),
                "last_message": self._last_sync_message,
            },
        }

    def get_attempts(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(connect(self._edge_db_path)) as conn:
            rows = conn.execute(
                "SELECT access_attempt_id, station_id, gate_id, direction, received_at, "
                "status, subject_id, reason_code "
                "FROM access_attempts ORDER BY received_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "access_attempt_id": r[0],
                "station_id": r[1],
                "gate_id": r[2],
                "direction": r[3],
                "received_at": _from_us(r[4]),
                "status": r[5],
                "subject_id": r[6],
                "reason_code": r[7],
            }
            for r in rows
        ]

    def get_attendance(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(connect(self._edge_db_path)) as conn:
            rows = conn.execute(
                "SELECT ar.transaction_id, ar.access_attempt_id, ar.employee_id, ar.factory_id, "
                "ar.station_id, ar.gate_id, ar.direction, ar.event_time, ar.confirmation_evidence, "
                "ar.time_quality, ar.source_sequence, ar.policy_version, ar.controller_ack, "
                "oe.sync_status "
                "FROM attendance_records ar "
                "JOIN outbox_events oe ON oe.transaction_id = ar.transaction_id "
                "ORDER BY ar.source_sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "transaction_id": r[0],
                "access_attempt_id": r[1],
                "employee_id": r[2],
                "factory_id": r[3],
                "station_id": r[4],
                "gate_id": r[5],
                "direction": r[6],
                "event_time": _from_us(r[7]),
                "confirmation_evidence": r[8],
                "time_quality": r[9],
                "source_sequence": r[10],
                "policy_version": r[11],
                "controller_ack": r[12],
                "sync_status": r[13],
            }
            for r in rows
        ]

    def get_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(connect(self._edge_db_path)) as conn:
            rows = conn.execute(
                "SELECT oe.transaction_id, oe.sync_status, oe.created_at, oe.rejection_reason, "
                "ar.employee_id, ar.gate_id, ar.source_sequence "
                "FROM outbox_events oe "
                "JOIN attendance_records ar ON ar.transaction_id = oe.transaction_id "
                "ORDER BY oe.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "transaction_id": r[0],
                "sync_status": r[1],
                "created_at": _from_us(r[2]),
                "rejection_reason": r[3],
                "employee_id": r[4],
                "gate_id": r[5],
                "source_sequence": r[6],
            }
            for r in rows
        ]

    def reset(self) -> dict[str, Any]:
        for base in (self._edge_db_path, self._hub_db_path):
            for suffix in ("", "-wal", "-shm"):
                target = Path(f"{base}{suffix}")
                if target.exists():
                    target.unlink()
        self._gate_scenario = "acked_with_passage"
        self._last_sync_message = "Demo state reset"
        self._init_components()
        return self.get_state()

    def _find_attendance_by_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with closing(connect(self._edge_db_path)) as conn:
            row = conn.execute(
                "SELECT ar.transaction_id, ar.source_sequence, ar.policy_version, "
                "ar.controller_ack, ar.confirmation_evidence, oe.sync_status "
                "FROM attendance_records ar "
                "JOIN outbox_events oe ON oe.transaction_id = ar.transaction_id "
                "WHERE ar.access_attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "transaction_id": row[0],
            "source_sequence": row[1],
            "policy_version": row[2],
            "controller_ack": row[3],
            "confirmation_evidence": row[4],
            "sync_status": row[5],
        }

    def _build_timeline(
        self, attempt: AccessAttempt, attendance: dict[str, Any] | None
    ) -> list[dict[str, str]]:
        reason = attempt.reason_code or ""
        status = attempt.status

        qr_failed = status is AttemptStatus.DENIED and reason.startswith("QR_")
        replay_failed = qr_failed and reason == "QR_REPLAYED"
        sig_failed = qr_failed and not replay_failed
        policy_failed = status is AttemptStatus.DENIED and not qr_failed

        unlock_failed = status in {
            AttemptStatus.UNLOCK_REJECTED,
            AttemptStatus.UNLOCK_TIMEOUT,
            AttemptStatus.UNLOCK_UNAVAILABLE,
        }
        passage_failed = status is AttemptStatus.PASSAGE_UNRESOLVED
        confirmed = status is AttemptStatus.PASSAGE_CONFIRMED

        steps = [
            (
                "1. QR Received",
                "completed",
                f"Station {attempt.station_id}, Gate {attempt.gate_id}",
            ),
            (
                "2. Signature & Claims Checked",
                "failed" if sig_failed else "completed",
                reason if sig_failed else "Ed25519 signature & required claims valid",
            ),
            (
                "3. Replay Decision",
                "skipped" if sig_failed else ("failed" if replay_failed else "completed"),
                "Skipped" if sig_failed else (reason if replay_failed else "jti accepted (unique)"),
            ),
            (
                "4. Access Policy Evaluated",
                "skipped" if qr_failed else ("failed" if policy_failed else "completed"),
                "Skipped"
                if qr_failed
                else (
                    f"{reason} (policy {attempt.policy_version})"
                    if policy_failed
                    else f"ALLOW (policy {attempt.policy_version})"
                ),
            ),
            (
                "5. AccessAttempt Persisted",
                "completed",
                f"SQLite access_attempts: {status.value}",
            ),
            (
                "6. Gate Unlock Result",
                "skipped"
                if status is AttemptStatus.DENIED
                else ("failed" if unlock_failed else "completed"),
                "Gate not called"
                if status is AttemptStatus.DENIED
                else (reason if unlock_failed else "GateAck.ACKNOWLEDGED"),
            ),
            (
                "7. Passage Confirmation Result",
                "skipped"
                if (status is AttemptStatus.DENIED or unlock_failed)
                else ("failed" if passage_failed else "completed"),
                "Skipped"
                if (status is AttemptStatus.DENIED or unlock_failed)
                else (reason if passage_failed else "PassageStatus.CONFIRMED"),
            ),
            (
                "8. Attendance + Outbox Persisted",
                "completed" if (confirmed and attendance is not None) else "skipped",
                (
                    f"tx={attendance['transaction_id'][:8]}..., seq={attendance['source_sequence']}"
                    if (confirmed and attendance is not None)
                    else "No attendance created"
                ),
            ),
            (
                "9. Hub Synchronization Status",
                (
                    "completed"
                    if (attendance and attendance["sync_status"] == "SYNCED")
                    else ("pending" if attendance else "skipped")
                ),
                (f"Outbox: {attendance['sync_status']}" if attendance else "No outbox event"),
            ),
        ]
        return [{"step": s, "state": st, "detail": d} for s, st, d in steps]


def _from_us(microseconds: int) -> str:
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=microseconds)).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def create_demo_app(demo_dir: Path | None = None) -> FastAPI:
    """Factory for `uvicorn tmc_access.config.demo_container:create_demo_app --factory`."""
    runtime = DemoRuntime(demo_dir=demo_dir)
    return create_demo_app_from_runtime(runtime)
