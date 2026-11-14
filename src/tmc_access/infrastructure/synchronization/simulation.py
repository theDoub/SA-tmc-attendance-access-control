"""Local simulation only: persisted receiver, network faults and real acknowledgements.

No production HTTP endpoint, transport authentication or Hub integration is implied.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Protocol

from tmc_access.domain.errors import SyncError
from tmc_access.domain.models import AttendanceRecord, RejectedEvent, SyncResult


def _payload(event: AttendanceRecord) -> str:
    if event.event_time.utcoffset() is None:
        raise SyncError("Simulation event time must be timezone-aware")
    fields = asdict(event)
    fields.pop("sync_status")  # Delivery state is not part of immutable event identity.
    fields["event_time"] = event.event_time.astimezone(UTC).isoformat(timespec="microseconds")
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


class SimulationReceiver(Protocol):
    def ingest(self, batch: list[AttendanceRecord]) -> SyncResult: ...


class SimulatedHubReceiver:
    """SQLite-backed simulation: acknowledge only committed event content."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rejections: dict[str, RejectedEvent] = {}
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS simulated_events "
                "(transaction_id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=0.1)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            return conn
        except sqlite3.Error:
            conn.close()
            raise

    def reject_event(self, transaction_id: str, reason: str, permanent: bool = True) -> None:
        if not reason.strip() or type(permanent) is not bool:
            raise ValueError("Explicit rejection reason and permanent flag required")
        self._rejections[transaction_id] = RejectedEvent(transaction_id, reason, permanent)

    def clear_rejection(self, transaction_id: str) -> None:
        self._rejections.pop(transaction_id, None)

    @property
    def event_count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT count(*) FROM simulated_events").fetchone()[0]

    def ingest(self, batch: list[AttendanceRecord]) -> SyncResult:
        accepted, rejected, conflicts = [], [], []
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                for event in batch:
                    content = _payload(event)
                    existing = conn.execute(
                        "SELECT payload FROM simulated_events WHERE transaction_id=?",
                        (event.transaction_id,),
                    ).fetchone()
                    if existing is not None:
                        if existing[0] == content:
                            accepted.append(event.transaction_id)
                        else:
                            conflicts.append(event.transaction_id)
                    elif event.transaction_id in self._rejections:
                        rejected.append(self._rejections[event.transaction_id])
                    else:
                        conn.execute(
                            "INSERT INTO simulated_events VALUES (?, ?)",
                            (event.transaction_id, content),
                        )
                        accepted.append(event.transaction_id)
        except sqlite3.Error as exc:
            raise SyncError("Simulated receiver storage failure; no success ACK") from exc
        return SyncResult(tuple(accepted), tuple(rejected), tuple(conflicts))


class SimulatedSyncClient:
    """Fault injection uses explicit state; reconnect never invents an ACK."""

    def __init__(self, receiver: SimulationReceiver) -> None:
        self._receiver = receiver
        self.connected = True
        self.lose_ack_once = False
        self.disconnect_after_events: int | None = None
        self.sent_batches: list[tuple[AttendanceRecord, ...]] = []

    def push_events(self, batch: list[AttendanceRecord]) -> SyncResult:
        self.sent_batches.append(tuple(batch))
        if not self.connected:
            raise SyncError("Simulated network disconnected")
        if self.disconnect_after_events is not None:
            count = self.disconnect_after_events
            if type(count) is not int or count < 0:
                raise ValueError("disconnect_after_events must be a nonnegative integer")
            self.disconnect_after_events = None
            self._receiver.ingest(batch[:count])
            self.connected = False
            raise SyncError("Simulated disconnection during delivery; ACK unavailable")
        result = self._receiver.ingest(batch)
        if self.lose_ack_once:
            self.lose_ack_once = False
            self.connected = False
            raise SyncError("Simulated ACK lost after receiver commit")
        return result
