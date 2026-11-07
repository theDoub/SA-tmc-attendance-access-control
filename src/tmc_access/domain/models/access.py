"""Access authorization and attempt types (lifecycle stages 2 and 6).

A1 refs: Table 10 (Access Control), Table 16 (evaluateAccess), section 5.3.2 (AccessAttempt).
An ALLOW decision authorizes a gate operation; it is NOT attendance (A1 section 3.5.3).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Direction(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class AccessDecisionKind(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class DenyReason(StrEnum):
    QR_REJECTED = "QR_REJECTED"
    NOT_AUTHORIZED_FOR_GATE = "NOT_AUTHORIZED_FOR_GATE"
    EMPLOYEE_INACTIVE = "EMPLOYEE_INACTIVE"
    POLICY_MISSING = "POLICY_MISSING"
    POLICY_STALE = "POLICY_STALE"


@dataclass(frozen=True)
class AccessDecision:
    kind: AccessDecisionKind
    reason: DenyReason | None = None
    policy_version: str | None = None
    stale_cache_used: bool = False

    def __post_init__(self) -> None:
        if self.kind is AccessDecisionKind.DENY and self.reason is None:
            raise ValueError("DENY decision requires a reason")
        if self.kind is AccessDecisionKind.ALLOW and self.reason is not None:
            raise ValueError("ALLOW decision must not carry a deny reason")


class AttemptStatus(StrEnum):
    """Progress of one scan through the lifecycle. Order is informative, not a state machine."""

    RECEIVED = "RECEIVED"
    DENIED = "DENIED"
    ALLOWED_PERSISTED = "ALLOWED_PERSISTED"
    UNLOCK_ACKNOWLEDGED = "UNLOCK_ACKNOWLEDGED"
    UNLOCK_REJECTED = "UNLOCK_REJECTED"
    UNLOCK_TIMEOUT = "UNLOCK_TIMEOUT"
    PASSAGE_CONFIRMED = "PASSAGE_CONFIRMED"
    PASSAGE_UNRESOLVED = "PASSAGE_UNRESOLVED"


@dataclass(frozen=True)
class ScanInput:
    """Scanner-to-kiosk input (A1 Table 24). `payload` is secret-like: never log it."""

    request_id: str
    station_id: str
    gate_id: str
    direction: Direction
    received_at: datetime
    payload: str

    def __repr__(self) -> str:
        return (
            f"ScanInput(request_id={self.request_id!r}, station_id={self.station_id!r}, "
            f"gate_id={self.gate_id!r}, direction={self.direction!r}, payload=<redacted>)"
        )


@dataclass(frozen=True)
class AccessAttempt:
    """Audit entity for one scan. Always retained, whatever the outcome (A1 Table 15)."""

    access_attempt_id: str
    station_id: str
    gate_id: str
    direction: Direction
    received_at: datetime
    status: AttemptStatus = AttemptStatus.RECEIVED
    subject_id: str | None = None
    reason_code: str | None = None
