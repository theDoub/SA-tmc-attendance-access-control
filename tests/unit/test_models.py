"""Invariants that keep lifecycle stages distinct (A1 section 5.3.2)."""

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from tmc_access.domain.models import (
    AccessAttempt,
    AccessDecision,
    AccessDecisionKind,
    AttendanceRecord,
    DenyReason,
    GateCommandResult,
    QrValidationOutcome,
    QrValidationResult,
    VerifiedCredential,
)


@pytest.mark.unit
def test_attempt_and_record_are_distinct_types() -> None:
    assert AccessAttempt is not AttendanceRecord
    assert "confirmation_evidence" in {f.name for f in fields(AttendanceRecord)}
    assert "confirmation_evidence" not in {f.name for f in fields(AccessAttempt)}


@pytest.mark.unit
def test_gate_command_result_carries_no_passage() -> None:
    assert "passage" not in {f.name for f in fields(GateCommandResult)}


@pytest.mark.unit
def test_valid_qr_result_requires_credential() -> None:
    with pytest.raises(ValueError):
        QrValidationResult(QrValidationOutcome.VALID)


@pytest.mark.unit
def test_rejected_qr_result_cannot_carry_credential() -> None:
    now = datetime.now(UTC)
    cred = VerifiedCredential("subj", "jti", "kv1", now, now)
    with pytest.raises(ValueError):
        QrValidationResult(QrValidationOutcome.EXPIRED, credential=cred)


@pytest.mark.unit
def test_deny_requires_reason_and_allow_forbids_it() -> None:
    with pytest.raises(ValueError):
        AccessDecision(AccessDecisionKind.DENY)
    with pytest.raises(ValueError):
        AccessDecision(
            AccessDecisionKind.ALLOW,
            reason=DenyReason.POLICY_STALE,
            policy_version="policy-v1",
        )
    with pytest.raises(ValueError):
        AccessDecision(AccessDecisionKind.ALLOW)


@pytest.mark.unit
def test_attendance_record_requires_valid_metadata() -> None:
    from tmc_access.domain.models import ConfirmationEvidence, Direction, GateAck

    now = datetime.now(UTC)
    naive = datetime.now()
    valid_kwargs = dict(
        transaction_id="00000000-0000-4000-8000-000000000001",
        access_attempt_id="att-1",
        employee_id="emp-1",
        factory_id="fact-1",
        station_id="st-1",
        gate_id="g-1",
        direction=Direction.ENTRY,
        event_time=now,
        confirmation_evidence=ConfirmationEvidence.PASSAGE_CONFIRMED,
        controller_ack=GateAck.ACKNOWLEDGED,
        source_sequence=1,
        policy_version="policy-v1",
    )
    rec = AttendanceRecord(**valid_kwargs)
    assert rec.source_sequence == 1
    assert rec.controller_ack == GateAck.ACKNOWLEDGED

    # missing/empty policy_version
    with pytest.raises(ValueError, match="policy version"):
        AttendanceRecord(**(valid_kwargs | {"policy_version": ""}))

    # naive datetime
    with pytest.raises(ValueError, match="timezone-aware"):
        AttendanceRecord(**(valid_kwargs | {"event_time": naive}))

    # non-positive or non-int source_sequence
    with pytest.raises(ValueError, match="positive integer source_sequence"):
        AttendanceRecord(**(valid_kwargs | {"source_sequence": 0}))
    with pytest.raises(ValueError, match="positive integer source_sequence"):
        AttendanceRecord(**(valid_kwargs | {"source_sequence": -5}))
