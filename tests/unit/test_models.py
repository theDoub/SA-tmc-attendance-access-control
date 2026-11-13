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
