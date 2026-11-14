"""One store-and-forward batch through domain ports. Owner: Bui Doan Minh Nhat.

Retry/backoff is NOT a concern of this class's contract: scheduling and backoff configuration
live in config and infrastructure.synchronization.
"""

from tmc_access.domain.errors import SyncError
from tmc_access.domain.interfaces import OutboxRepository, SyncClient
from tmc_access.domain.models import RejectedEvent, SyncResult


class SyncService:
    def __init__(self, outbox: OutboxRepository, client: SyncClient, batch_size: int = 100) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self._outbox = outbox
        self._client = client
        self._batch_size = batch_size

    def sync_once(self) -> None:
        batch = self._outbox.get_pending(self._batch_size)
        if not batch:
            return
        result = self._client.push_events(batch)
        if not isinstance(result, SyncResult):
            raise SyncError("Invalid sync response")
        if not all(
            isinstance(part, tuple)
            for part in (result.accepted_ids, result.rejected, result.conflict_ids)
        ) or any(not isinstance(item, RejectedEvent) for item in result.rejected):
            raise SyncError("Invalid sync response fields")
        sent = {event.transaction_id for event in batch}
        reported = list(result.accepted_ids) + list(result.conflict_ids)
        reported.extend(item.transaction_id for item in result.rejected)
        if any(not isinstance(value, str) or not value.strip() for value in reported):
            raise SyncError("Invalid sync response identifiers")
        if len(reported) != len(set(reported)) or not set(reported) <= sent:
            raise SyncError("Sync response contains duplicate, overlapping or unknown IDs")
        if any(
            type(item.permanent) is not bool
            or not isinstance(item.reason, str)
            or not item.reason.strip()
            for item in result.rejected
        ):
            raise SyncError("Invalid rejection response")
        # Validate the complete acknowledgement before changing any queue state.
        self._outbox.mark_synchronized(list(result.accepted_ids))
        for item in result.rejected:
            if item.permanent:
                self._outbox.mark_rejected(item.transaction_id, item.reason)
        for transaction_id in result.conflict_ids:
            self._outbox.mark_conflict(transaction_id)
        if set(reported) != sent or any(not item.permanent for item in result.rejected):
            raise SyncError("Some events remain pending after partial or transient rejection")
