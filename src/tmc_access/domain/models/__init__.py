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
    "AttemptStatus",
    "AttendanceRecord",
    "ConfirmationEvidence",
    "DenyReason",
    "Direction",
    "GateAck",
    "GateCommandResult",
    "PassageStatus",
    "QrValidationOutcome",
    "QrValidationResult",
    "RejectedEvent",
    "ScanInput",
    "SyncResult",
    "SyncStatus",
    "TimeQuality",
    "VerifiedCredential",
]
