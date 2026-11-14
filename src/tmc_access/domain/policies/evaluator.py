"""Pure evaluation of the active local access-policy snapshot."""

from datetime import datetime, timedelta
from typing import Protocol

from tmc_access.domain.errors import PolicyError
from tmc_access.domain.models import (
    AccessDecision,
    AccessDecisionKind,
    DenyReason,
    Direction,
    PolicySnapshot,
    VerifiedCredential,
)


class PolicySnapshotProvider(Protocol):
    """Outer-layer source for the latest locally cached policy snapshot."""

    def get_snapshot(self) -> PolicySnapshot | None:
        """Return the active snapshot, or ``None`` when no cache exists.

        Raises:
            PolicyError: the cached snapshot cannot be read or decoded.
        """
        ...


class AccessPolicyEvaluator:
    """Satisfies ``AccessPolicyEngine`` without performing network access."""

    def __init__(
        self,
        snapshot_provider: PolicySnapshotProvider | None,
        *,
        fresh_for: timedelta,
        max_stale_for: timedelta,
    ) -> None:
        if fresh_for < timedelta(0):
            raise ValueError("fresh_for must not be negative")
        if max_stale_for < fresh_for:
            raise ValueError("max_stale_for must be at least fresh_for")
        self._snapshot_provider = snapshot_provider
        self._fresh_for = fresh_for
        self._max_stale_for = max_stale_for

    def evaluate(
        self,
        credential: VerifiedCredential,
        gate_id: str,
        direction: Direction,
        now: datetime,
    ) -> AccessDecision:
        if now.tzinfo is None:
            raise PolicyError("policy evaluation time must be timezone-aware")

        snapshot = self._load_snapshot()
        if snapshot is None:
            return AccessDecision(AccessDecisionKind.DENY, reason=DenyReason.POLICY_MISSING)

        age = now - snapshot.refreshed_at
        if age < timedelta(0):
            raise PolicyError("policy snapshot refresh time is in the future")
        if age > self._max_stale_for:
            return AccessDecision(
                AccessDecisionKind.DENY,
                reason=DenyReason.POLICY_STALE,
                policy_version=snapshot.version,
            )

        stale_cache_used = age > self._fresh_for
        subject_policy = snapshot.policy_for(credential.subject_id)
        if subject_policy is None:
            return AccessDecision(
                AccessDecisionKind.DENY,
                reason=DenyReason.NOT_AUTHORIZED_FOR_GATE,
                policy_version=snapshot.version,
                stale_cache_used=stale_cache_used,
            )
        if not subject_policy.active:
            return AccessDecision(
                AccessDecisionKind.DENY,
                reason=DenyReason.EMPLOYEE_INACTIVE,
                policy_version=snapshot.version,
                stale_cache_used=stale_cache_used,
            )
        if not subject_policy.allows(gate_id, direction, now):
            return AccessDecision(
                AccessDecisionKind.DENY,
                reason=DenyReason.NOT_AUTHORIZED_FOR_GATE,
                policy_version=snapshot.version,
                stale_cache_used=stale_cache_used,
            )
        return AccessDecision(
            AccessDecisionKind.ALLOW,
            policy_version=snapshot.version,
            stale_cache_used=stale_cache_used,
        )

    def _load_snapshot(self) -> PolicySnapshot | None:
        if self._snapshot_provider is None:
            return None
        try:
            return self._snapshot_provider.get_snapshot()
        except PolicyError:
            raise
        except Exception as exc:
            raise PolicyError("policy snapshot could not be loaded") from exc
