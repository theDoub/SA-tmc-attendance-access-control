"""Synchronization status and result types (lifecycle stage 7).

A1 refs: sections 3.5.5, 4.3.5 / Table 31. Retry/backoff settings are NOT here; they are
operational configuration (config + infrastructure).
"""

from dataclasses import dataclass
from enum import StrEnum


class SyncStatus(StrEnum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class RejectedEvent:
    transaction_id: str
    reason: str
    permanent: bool


@dataclass(frozen=True)
class SyncResult:
    """Hub answer for a batch. Only `accepted_ids` may be marked SYNCED."""

    accepted_ids: tuple[str, ...] = ()
    rejected: tuple[RejectedEvent, ...] = ()
    conflict_ids: tuple[str, ...] = ()
