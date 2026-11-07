"""Access policy evaluator placeholder. TODO(Kim): implement the A1 `evaluateAccess` rules."""

from datetime import datetime

from tmc_access.domain.models import AccessDecision, Direction, VerifiedCredential


class AccessPolicyEvaluator:
    """Satisfies `AccessPolicyEngine`. Not implemented: raising is the only honest behaviour."""

    def evaluate(
        self,
        credential: VerifiedCredential,
        gate_id: str,
        direction: Direction,
        now: datetime,
    ) -> AccessDecision:
        raise NotImplementedError("TODO(Kim): access policy evaluation")
