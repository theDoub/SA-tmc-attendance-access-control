"""Persistence ports. Owner: Bui Doan Minh Nhat.

Proposed (pending team confirmation, OD-04): attempt persisted -> unlock -> passage ->
AttendanceRecord + outbox entry persisted atomically in ONE local transaction.
A1 Figure 4 step 4B shows "attempt + pending outbox" before the unlock; the difference is OD-04.
"""

from typing import Protocol

from tmc_access.domain.models import AccessAttempt, AttendanceRecord


class AttendanceRepository(Protocol):
    def save_attempt(self, attempt: AccessAttempt) -> None:
        """Durably insert an attempt (all outcomes, including denials, for audit).

        Raises:
            StorageError: write failed. The caller must NOT issue an unlock command
                (A1 Table 32) and must not claim success.
        """
        ...

    def update_attempt(self, attempt: AccessAttempt) -> None:
        """Persist a status transition of an existing attempt.

        Raises:
            StorageError: write failed.
        """
        ...

    def save_record_with_outbox(self, record: AttendanceRecord) -> None:
        """Insert the AttendanceRecord and its outbox entry atomically (all or nothing).

        Idempotent on `record.transaction_id`: re-saving the same id must not duplicate.

        Raises:
            StorageError: transaction failed; neither row may exist afterwards.
        """
        ...


class OutboxRepository(Protocol):
    def get_pending(self, batch_size: int) -> list[AttendanceRecord]:
        """Oldest pending records first. Never returns SYNCED/REJECTED/CONFLICT items."""
        ...

    def mark_synchronized(self, transaction_ids: list[str]) -> None:
        """Only for ids the Hub acknowledged as accepted (A1 Table 31)."""
        ...

    def mark_rejected(self, transaction_id: str, reason: str) -> None:
        """Quarantine a permanently invalid record; stop automatic retries for it."""
        ...

    def mark_conflict(self, transaction_id: str) -> None:
        """Duplicate id with conflicting content: keep for investigation, never SYNCED."""
        ...
