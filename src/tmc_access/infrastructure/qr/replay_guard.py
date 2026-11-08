"""Process-local replay simulation. Restart and other processes are outside its scope."""

from datetime import datetime
from threading import Lock


class ReplayGuardStore:
    def __init__(self):
        self._seen: dict[str, datetime] = {}
        self._lock = Lock()

    def check_and_record(self, token_id: str, expires_at: datetime, now: datetime) -> bool:
        with self._lock:
            self._seen = {key: exp for key, exp in self._seen.items() if exp > now}
            if token_id in self._seen or expires_at <= now:
                return False
            self._seen[token_id] = expires_at
            return True
