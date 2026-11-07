"""Store-and-forward sync service skeleton. Owner: Bui Doan Minh Nhat.

Retry/backoff is NOT a concern of this class's contract: scheduling and backoff configuration
live in config and infrastructure.synchronization.
"""

from tmc_access.domain.interfaces import OutboxRepository, SyncClient


class SyncService:
    def __init__(self, outbox: OutboxRepository, client: SyncClient) -> None:
        self._outbox = outbox
        self._client = client

    def sync_once(self) -> None:
        raise NotImplementedError("TODO(Nhat): push pending outbox batch and apply the Hub ack")
