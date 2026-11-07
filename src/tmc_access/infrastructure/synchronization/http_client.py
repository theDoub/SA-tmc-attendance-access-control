"""Hub sync client placeholder. TODO(Nhat). Hub API schema and transport auth are undecided
(OD-10); do not invent them here."""

from tmc_access.domain.models import AttendanceRecord, SyncResult


class HttpSyncClient:
    """Satisfies `SyncClient`."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def push_events(self, batch: list[AttendanceRecord]) -> SyncResult:
        raise NotImplementedError("TODO(Nhat): Hub ingestion client (OD-10)")
