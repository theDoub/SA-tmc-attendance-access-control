"""Synchronization port. Owner: Bui Doan Minh Nhat. Hub API schema is NOT defined here (A1 only
names `syncEvents`); transport security is OD-10."""

from typing import Protocol

from tmc_access.domain.models import AttendanceRecord, SyncResult


class SyncClient(Protocol):
    """A1 `IAttendanceSyncClient` / contract `syncEvents`."""

    def push_events(self, batch: list[AttendanceRecord]) -> SyncResult:
        """Deliver a batch at-least-once; the Hub is idempotent on `transaction_id`.

        Returns accepted / rejected / conflict ids. A duplicate with identical content is
        reported as accepted (A1 Table 31).

        Raises:
            SyncError: transient failure (network, timeout, 5xx, auth). Records stay PENDING.
        """
        ...
