"""Decision-flow scenarios owned by Nguyen Ngoc Kim."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.domain.errors import StorageError
from tmc_access.domain.models import (
    AccessAttempt,
    AccessDecision,
    AccessDecisionKind,
    AttemptStatus,
    AttendanceRecord,
    ConfirmationEvidence,
    DenyReason,
    Direction,
    QrValidationOutcome,
    QrValidationResult,
    ScanInput,
    VerifiedCredential,
)
from tmc_access.infrastructure.turnstile.mock_turnstile import (
    MockScenario,
    MockTurnstileAdapter,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
EVENT_TIME = NOW + timedelta(seconds=2)
TRANSACTION_ID = UUID("00000000-0000-4000-8000-000000000001")
CREDENTIAL = VerifiedCredential(
    subject_id="employee-001",
    token_id="token-001",
    key_version="key-v1",
    issued_at=NOW - timedelta(seconds=10),
    expires_at=NOW + timedelta(seconds=50),
)
SCAN = ScanInput("request-001", "station-1", "gate-1", Direction.ENTRY, NOW, "synthetic")


class FixedValidator:
    def __init__(self, result: QrValidationResult) -> None:
        self.result = result

    def validate(self, raw_payload: str, station_id: str, now: datetime) -> QrValidationResult:
        return self.result


class FixedPolicyEngine:
    def __init__(self, decision: AccessDecision) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(
        self,
        credential: VerifiedCredential,
        gate_id: str,
        direction: Direction,
        now: datetime,
    ) -> AccessDecision:
        self.calls += 1
        return self.decision


class RecordingRepository:
    def __init__(self, *, fail_first_save: bool = False) -> None:
        self.fail_first_save = fail_first_save
        self.saved_attempts: list[AccessAttempt] = []
        self.updated_attempts: list[AccessAttempt] = []
        self.records: list[AttendanceRecord] = []
        self.last_sequence = 0

    def next_sequence(self) -> int:
        self.last_sequence += 1
        return self.last_sequence

    def save_attempt(self, attempt: AccessAttempt) -> None:
        if self.fail_first_save:
            raise StorageError("synthetic disk failure")
        self.saved_attempts.append(attempt)

    def update_attempt(self, attempt: AccessAttempt) -> None:
        self.updated_attempts.append(attempt)

    def save_record_with_outbox(self, record: AttendanceRecord) -> None:
        self.records.append(record)


def valid_result() -> QrValidationResult:
    return QrValidationResult(QrValidationOutcome.VALID, credential=CREDENTIAL)


def build_coordinator(
    *,
    gate: MockTurnstileAdapter,
    repository: RecordingRepository,
    decision: AccessDecision | None = None,
    validation: QrValidationResult | None = None,
) -> tuple[AccessCoordinator, FixedPolicyEngine]:
    policy = FixedPolicyEngine(
        decision
        or AccessDecision(
            AccessDecisionKind.ALLOW,
            policy_version="policy-v7",
        )
    )
    coordinator = AccessCoordinator(
        validator=FixedValidator(validation or valid_result()),
        policy_engine=policy,
        gate=gate,
        attendance_repository=repository,
        factory_id="factory-1",
        turnstile_timeout_ms=800,
        passage_window_seconds=15,
        clock=lambda: EVENT_TIME,
        uuid_factory=lambda: TRANSACTION_ID,
    )
    return coordinator, policy


@pytest.mark.unit
def test_access_denied_by_policy_does_not_call_gate() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    repository = RecordingRepository()
    coordinator, _ = build_coordinator(
        gate=gate,
        repository=repository,
        decision=AccessDecision(
            AccessDecisionKind.DENY,
            reason=DenyReason.NOT_AUTHORIZED_FOR_GATE,
            policy_version="policy-v7",
        ),
    )

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.status is AttemptStatus.DENIED
    assert attempt.reason_code == DenyReason.NOT_AUTHORIZED_FOR_GATE.value
    assert repository.saved_attempts == [attempt]
    assert repository.records == []
    assert gate.issued_commands == {}


@pytest.mark.unit
def test_rejected_qr_is_audited_without_policy_or_gate_call() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    repository = RecordingRepository()
    coordinator, policy = build_coordinator(
        gate=gate,
        repository=repository,
        validation=QrValidationResult(QrValidationOutcome.EXPIRED),
    )

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.status is AttemptStatus.DENIED
    assert attempt.reason_code == "QR_EXPIRED"
    assert policy.calls == 0
    assert gate.issued_commands == {}


@pytest.mark.unit
def test_failed_attempt_persistence_prevents_unlock() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    repository = RecordingRepository(fail_first_save=True)
    coordinator, _ = build_coordinator(gate=gate, repository=repository)

    with pytest.raises(StorageError, match="disk failure"):
        coordinator.handle_scan(SCAN)

    assert gate.issued_commands == {}
    assert repository.records == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        (MockScenario.rejected(), AttemptStatus.UNLOCK_REJECTED),
        (MockScenario.timeout(), AttemptStatus.UNLOCK_TIMEOUT),
        (MockScenario.unavailable(), AttemptStatus.UNLOCK_UNAVAILABLE),
    ],
)
def test_gate_command_failure_is_not_attendance(
    scenario: MockScenario, expected_status: AttemptStatus
) -> None:
    gate = MockTurnstileAdapter(scenario)
    repository = RecordingRepository()
    coordinator, _ = build_coordinator(gate=gate, repository=repository)

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.status is expected_status
    assert repository.records == []


@pytest.mark.unit
def test_ack_without_passage_is_not_attendance() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_no_passage())
    repository = RecordingRepository()
    coordinator, _ = build_coordinator(gate=gate, repository=repository)

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.status is AttemptStatus.PASSAGE_UNRESOLVED
    assert attempt.reason_code == "PASSAGE_NOT_CONFIRMED"
    assert repository.records == []


@pytest.mark.unit
def test_confirmed_passage_creates_linked_attendance_and_outbox_record() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    repository = RecordingRepository()
    coordinator, _ = build_coordinator(gate=gate, repository=repository)

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.status is AttemptStatus.PASSAGE_CONFIRMED
    assert attempt.policy_version == "policy-v7"
    assert len(repository.records) == 1
    record = repository.records[0]
    assert record.transaction_id == str(TRANSACTION_ID)
    assert record.access_attempt_id == attempt.access_attempt_id
    assert record.employee_id == CREDENTIAL.subject_id
    assert record.event_time == EVENT_TIME
    assert record.confirmation_evidence is ConfirmationEvidence.PASSAGE_CONFIRMED
    assert record.controller_ack.value == "ACKNOWLEDGED"
    assert record.policy_version == "policy-v7"
    assert record.source_sequence == 1


@pytest.mark.unit
def test_stale_policy_metadata_is_retained_on_attempt() -> None:
    gate = MockTurnstileAdapter(MockScenario.rejected())
    repository = RecordingRepository()
    coordinator, _ = build_coordinator(
        gate=gate,
        repository=repository,
        decision=AccessDecision(
            AccessDecisionKind.ALLOW,
            policy_version="policy-v6",
            stale_cache_used=True,
        ),
    )

    attempt = coordinator.handle_scan(SCAN)

    assert attempt.policy_version == "policy-v6"
    assert attempt.stale_cache_used is True
