"""Attendance record (lifecycle stage 5). Distinct from AccessAttempt.

A1 refs: Table 30 (durable local transaction schema), ADR-003 (transaction_id UUIDv4),
section 5.3.2. Creation rule is Proposed / Pending (OD-04, OD-05).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tmc_access.domain.models.access import Direction
from tmc_access.domain.models.gate import GateAck
from tmc_access.domain.models.sync import SyncStatus


class ConfirmationEvidence(StrEnum):
    PASSAGE_CONFIRMED = "PASSAGE_CONFIRMED"
    # Only if the team adopts the A1 section 3.5.3 fallback (OD-05); must stay flagged.
    CONTROLLER_ACK_ONLY = "CONTROLLER_ACK_ONLY"


class TimeQuality(StrEnum):
    RELIABLE = "RELIABLE"
    UNRELIABLE = "UNRELIABLE"


@dataclass(frozen=True)
class AttendanceRecord:
    """`transaction_id` is the stable idempotency key (UUIDv4 per ADR-003; naming is OD-06)."""

    transaction_id: str
    access_attempt_id: str
    employee_id: str
    factory_id: str
    station_id: str
    gate_id: str
    direction: Direction
    event_time: datetime
    confirmation_evidence: ConfirmationEvidence
    controller_ack: GateAck
    policy_version: str
    time_quality: TimeQuality = TimeQuality.RELIABLE
    sync_status: SyncStatus = SyncStatus.PENDING

    def __post_init__(self) -> None:
        if not self.policy_version:
            raise ValueError("attendance record requires a policy version")
        if self.event_time.tzinfo is None:
            raise ValueError("attendance event time must be timezone-aware")
