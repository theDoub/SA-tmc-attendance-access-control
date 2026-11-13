"""Domain model types. Each lifecycle stage has its own type; none implies the next.

See docs/contracts/edge-access-contracts.md (section "Attendance lifecycle").
"""

from tmc_access.domain.models.access import (
    AccessAttempt,
    AccessDecision,
    AccessDecisionKind,
    AttemptStatus,
    DenyReason,
    Direction,
    ScanInput,
)
from tmc_access.domain.models.attendance import (
    AttendanceRecord,
    ConfirmationEvidence,
    TimeQuality,
)
from tmc_access.domain.models.gate import GateAck, GateCommandResult, PassageStatus
from tmc_access.domain.models.policy import AccessGrant, PolicySnapshot, SubjectPolicy
from tmc_access.domain.models.qr import (
    QrValidationOutcome,
    QrValidationResult,
    VerifiedCredential,
)
from tmc_access.domain.models.sync import RejectedEvent, SyncResult, SyncStatus

__all__ = [
    "AccessAttempt",
    "AccessDecision",
    "AccessDecisionKind",
    "AccessGrant",
    "AttemptStatus",
    "AttendanceRecord",
    "ConfirmationEvidence",
    "DenyReason",
    "Direction",
    "GateAck",
    "GateCommandResult",
    "PassageStatus",
    "PolicySnapshot",
    "QrValidationOutcome",
    "QrValidationResult",
    "RejectedEvent",
    "ScanInput",
    "SyncResult",
    "SyncStatus",
    "SubjectPolicy",
    "TimeQuality",
    "VerifiedCredential",
]
