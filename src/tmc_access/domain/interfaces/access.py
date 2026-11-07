"""Access authorization port. Owner: Nguyen Ngoc Kim."""

from datetime import datetime
from typing import Protocol

from tmc_access.domain.models import AccessDecision, Direction, VerifiedCredential


class AccessPolicyEngine(Protocol):
    """A1 contract `evaluateAccess` (Table 16)."""

    def evaluate(
        self,
        credential: VerifiedCredential,
        gate_id: str,
        direction: Direction,
        now: datetime,
    ) -> AccessDecision:
        """Return ALLOW or DENY with a reason, using the local active policy snapshot.

        A DENY (including stale/missing policy) is a normal result, not an exception.
        The engine does not touch the turnstile and does not create attendance.

        Raises:
            PolicyError: policy data is corrupt/unreadable (not merely "employee denied").
        """
        ...
