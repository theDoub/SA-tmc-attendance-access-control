"""Access policy rules owned by Nguyen Ngoc Kim."""

from datetime import UTC, datetime, timedelta

import pytest

from tmc_access.domain.errors import PolicyError
from tmc_access.domain.models import (
    AccessDecisionKind,
    AccessGrant,
    DenyReason,
    Direction,
    PolicySnapshot,
    SubjectPolicy,
    VerifiedCredential,
)
from tmc_access.domain.policies import AccessPolicyEvaluator

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
CREDENTIAL = VerifiedCredential(
    subject_id="employee-001",
    token_id="token-001",
    key_version="key-v1",
    issued_at=NOW - timedelta(seconds=10),
    expires_at=NOW + timedelta(seconds=50),
)


class FixedProvider:
    def __init__(self, snapshot: PolicySnapshot | None) -> None:
        self.snapshot = snapshot

    def get_snapshot(self) -> PolicySnapshot | None:
        return self.snapshot


class BrokenProvider:
    def get_snapshot(self) -> PolicySnapshot | None:
        raise OSError("synthetic unreadable cache")


def snapshot(
    *,
    age: timedelta = timedelta(minutes=1),
    active: bool = True,
    grants: frozenset[AccessGrant] | None = None,
) -> PolicySnapshot:
    if grants is None:
        grants = frozenset({AccessGrant("gate-1", Direction.ENTRY)})
    return PolicySnapshot(
        version="policy-v7",
        refreshed_at=NOW - age,
        subjects=(SubjectPolicy(CREDENTIAL.subject_id, active, grants),),
    )


def evaluator(provider: FixedProvider | BrokenProvider | None) -> AccessPolicyEvaluator:
    return AccessPolicyEvaluator(
        provider,
        fresh_for=timedelta(minutes=5),
        max_stale_for=timedelta(hours=2),
    )


@pytest.mark.unit
def test_fresh_matching_policy_allows_access() -> None:
    result = evaluator(FixedProvider(snapshot())).evaluate(
        CREDENTIAL, "gate-1", Direction.ENTRY, NOW
    )

    assert result.kind is AccessDecisionKind.ALLOW
    assert result.policy_version == "policy-v7"
    assert result.stale_cache_used is False


@pytest.mark.unit
def test_stale_but_usable_policy_records_stale_cache() -> None:
    result = evaluator(FixedProvider(snapshot(age=timedelta(minutes=30)))).evaluate(
        CREDENTIAL, "gate-1", Direction.ENTRY, NOW
    )

    assert result.kind is AccessDecisionKind.ALLOW
    assert result.stale_cache_used is True


@pytest.mark.unit
def test_snapshot_older_than_two_hours_denies() -> None:
    result = evaluator(FixedProvider(snapshot(age=timedelta(hours=2, seconds=1)))).evaluate(
        CREDENTIAL, "gate-1", Direction.ENTRY, NOW
    )

    assert result.kind is AccessDecisionKind.DENY
    assert result.reason is DenyReason.POLICY_STALE
    assert result.policy_version == "policy-v7"


@pytest.mark.unit
def test_missing_snapshot_denies() -> None:
    result = evaluator(FixedProvider(None)).evaluate(CREDENTIAL, "gate-1", Direction.ENTRY, NOW)

    assert result.kind is AccessDecisionKind.DENY
    assert result.reason is DenyReason.POLICY_MISSING


@pytest.mark.unit
def test_inactive_subject_denies() -> None:
    result = evaluator(FixedProvider(snapshot(active=False))).evaluate(
        CREDENTIAL, "gate-1", Direction.ENTRY, NOW
    )

    assert result.kind is AccessDecisionKind.DENY
    assert result.reason is DenyReason.EMPLOYEE_INACTIVE


@pytest.mark.unit
@pytest.mark.parametrize(
    ("gate_id", "direction"),
    [("gate-2", Direction.ENTRY), ("gate-1", Direction.EXIT)],
)
def test_non_matching_gate_or_direction_denies(gate_id: str, direction: Direction) -> None:
    result = evaluator(FixedProvider(snapshot())).evaluate(CREDENTIAL, gate_id, direction, NOW)

    assert result.kind is AccessDecisionKind.DENY
    assert result.reason is DenyReason.NOT_AUTHORIZED_FOR_GATE


@pytest.mark.unit
def test_grant_outside_its_time_window_denies() -> None:
    future_grant = AccessGrant(
        "gate-1",
        Direction.ENTRY,
        valid_from=NOW + timedelta(hours=1),
        valid_until=NOW + timedelta(hours=2),
    )
    result = evaluator(FixedProvider(snapshot(grants=frozenset({future_grant})))).evaluate(
        CREDENTIAL, "gate-1", Direction.ENTRY, NOW
    )

    assert result.kind is AccessDecisionKind.DENY
    assert result.reason is DenyReason.NOT_AUTHORIZED_FOR_GATE


@pytest.mark.unit
def test_unreadable_snapshot_is_a_policy_error() -> None:
    with pytest.raises(PolicyError, match="could not be loaded"):
        evaluator(BrokenProvider()).evaluate(CREDENTIAL, "gate-1", Direction.ENTRY, NOW)


@pytest.mark.unit
def test_future_dated_snapshot_is_rejected() -> None:
    future = snapshot(age=timedelta(seconds=-1))

    with pytest.raises(PolicyError, match="future"):
        evaluator(FixedProvider(future)).evaluate(CREDENTIAL, "gate-1", Direction.ENTRY, NOW)
