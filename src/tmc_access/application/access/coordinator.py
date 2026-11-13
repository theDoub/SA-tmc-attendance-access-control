"""Gate access decision flow. Owner: Nguyen Ngoc Kim.

Depends only on domain abstractions (DIP). Intended flow, PROPOSED and pending team
confirmation (OD-04, OD-05): validate QR -> evaluate policy -> persist attempt -> unlock ->
query passage -> persist AttendanceRecord + outbox atomically.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from tmc_access.domain.errors import GateError, PolicyError, QrError, StorageError
from tmc_access.domain.interfaces import (
    AccessPolicyEngine,
    AttendanceRepository,
    GateAdapter,
    QrValidator,
)
from tmc_access.domain.models import (
    AccessAttempt,
    AccessDecisionKind,
    AttemptStatus,
    AttendanceRecord,
    ConfirmationEvidence,
    GateAck,
    PassageStatus,
    QrValidationResult,
    ScanInput,
)


class AccessCoordinator:
    def __init__(
        self,
        validator: QrValidator,
        policy_engine: AccessPolicyEngine,
        gate: GateAdapter,
        attendance_repository: AttendanceRepository,
        *,
        factory_id: str,
        turnstile_timeout_ms: int,
        passage_window_seconds: int,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if not factory_id:
            raise ValueError("factory_id must not be empty")
        if turnstile_timeout_ms <= 0:
            raise ValueError("turnstile_timeout_ms must be positive")
        if passage_window_seconds <= 0:
            raise ValueError("passage_window_seconds must be positive")
        self._validator = validator
        self._policy_engine = policy_engine
        self._gate = gate
        self._attendance_repository = attendance_repository
        self._factory_id = factory_id
        self._turnstile_timeout_ms = turnstile_timeout_ms
        self._passage_window_seconds = passage_window_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uuid_factory = uuid_factory

    def handle_scan(self, scan: ScanInput) -> AccessAttempt:
        """Process one scan without depending on Hub availability.

        The ordering follows the documented OD-04 bootstrap assumption.  A durable allowed
        attempt is required before unlock, and only confirmed passage creates attendance.
        """
        attempt = AccessAttempt(
            access_attempt_id=scan.request_id,
            station_id=scan.station_id,
            gate_id=scan.gate_id,
            direction=scan.direction,
            received_at=scan.received_at,
        )

        validation = self._validate(scan, attempt)
        if not validation.is_valid:
            denied = replace(
                attempt,
                status=AttemptStatus.DENIED,
                reason_code=f"QR_{validation.outcome.value}",
            )
            self._attendance_repository.save_attempt(denied)
            return denied

        credential = validation.credential
        assert credential is not None  # enforced by QrValidationResult
        attempt = replace(attempt, subject_id=credential.subject_id)

        try:
            decision = self._policy_engine.evaluate(
                credential,
                scan.gate_id,
                scan.direction,
                scan.received_at,
            )
        except PolicyError:
            failed = replace(
                attempt,
                status=AttemptStatus.DENIED,
                reason_code="POLICY_PROCESSING_ERROR",
            )
            self._attendance_repository.save_attempt(failed)
            raise

        attempt = replace(
            attempt,
            policy_version=decision.policy_version,
            stale_cache_used=decision.stale_cache_used,
        )
        if decision.kind is AccessDecisionKind.DENY:
            denied = replace(
                attempt,
                status=AttemptStatus.DENIED,
                reason_code=decision.reason.value if decision.reason else "POLICY_DENIED",
            )
            self._attendance_repository.save_attempt(denied)
            return denied

        policy_version = decision.policy_version
        assert policy_version is not None  # enforced by AccessDecision for ALLOW
        allowed = replace(attempt, status=AttemptStatus.ALLOWED_PERSISTED)
        # A failed durable write must stop the flow before the gate command.
        self._attendance_repository.save_attempt(allowed)

        try:
            gate_result = self._gate.unlock(
                command_id=allowed.access_attempt_id,
                gate_id=scan.gate_id,
                direction=scan.direction,
                timeout_ms=self._turnstile_timeout_ms,
            )
        except GateError:
            failed = replace(
                allowed,
                status=AttemptStatus.UNLOCK_UNAVAILABLE,
                reason_code="GATE_PROCESSING_ERROR",
            )
            self._attendance_repository.update_attempt(failed)
            raise

        if gate_result.ack is GateAck.REJECTED:
            return self._update_attempt(allowed, AttemptStatus.UNLOCK_REJECTED, "GATE_REJECTED")
        if gate_result.ack is GateAck.TIMEOUT:
            return self._update_attempt(allowed, AttemptStatus.UNLOCK_TIMEOUT, "GATE_TIMEOUT")
        if gate_result.ack is GateAck.UNAVAILABLE:
            return self._update_attempt(
                allowed, AttemptStatus.UNLOCK_UNAVAILABLE, "GATE_UNAVAILABLE"
            )

        acknowledged = self._update_attempt(allowed, AttemptStatus.UNLOCK_ACKNOWLEDGED, None)
        try:
            passage = self._gate.query_passage(
                gate_result.command_id,
                window_seconds=self._passage_window_seconds,
            )
        except GateError:
            unresolved = replace(
                acknowledged,
                status=AttemptStatus.PASSAGE_UNRESOLVED,
                reason_code="PASSAGE_QUERY_ERROR",
            )
            self._attendance_repository.update_attempt(unresolved)
            raise

        if passage is not PassageStatus.CONFIRMED:
            return self._update_attempt(
                acknowledged,
                AttemptStatus.PASSAGE_UNRESOLVED,
                f"PASSAGE_{passage.value}",
            )

        confirmed = self._update_attempt(acknowledged, AttemptStatus.PASSAGE_CONFIRMED, None)
        event_time = self._clock()
        if event_time.tzinfo is None:
            raise ValueError("attendance clock must return a timezone-aware datetime")
        record = AttendanceRecord(
            transaction_id=str(self._uuid_factory()),
            access_attempt_id=confirmed.access_attempt_id,
            employee_id=credential.subject_id,
            factory_id=self._factory_id,
            station_id=scan.station_id,
            gate_id=scan.gate_id,
            direction=scan.direction,
            event_time=event_time,
            confirmation_evidence=ConfirmationEvidence.PASSAGE_CONFIRMED,
            controller_ack=GateAck.ACKNOWLEDGED,
            policy_version=policy_version,
        )
        self._attendance_repository.save_record_with_outbox(record)
        return confirmed

    def _validate(self, scan: ScanInput, attempt: AccessAttempt) -> QrValidationResult:
        try:
            return self._validator.validate(scan.payload, scan.station_id, scan.received_at)
        except QrError:
            failed = replace(
                attempt,
                status=AttemptStatus.DENIED,
                reason_code="QR_PROCESSING_ERROR",
            )
            self._attendance_repository.save_attempt(failed)
            raise
        except StorageError:
            failed = replace(
                attempt,
                status=AttemptStatus.DENIED,
                reason_code="QR_REPLAY_STATE_UNAVAILABLE",
            )
            self._attendance_repository.save_attempt(failed)
            raise

    def _update_attempt(
        self,
        attempt: AccessAttempt,
        status: AttemptStatus,
        reason_code: str | None,
    ) -> AccessAttempt:
        updated = replace(attempt, status=status, reason_code=reason_code)
        self._attendance_repository.update_attempt(updated)
        return updated
