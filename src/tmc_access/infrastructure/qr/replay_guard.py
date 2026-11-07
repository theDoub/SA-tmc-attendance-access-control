"""Replay guard placeholder. TODO(Hieu): storage strategy is OD-08."""

from datetime import datetime


class ReplayGuardStore:
    """Satisfies `ReplayGuard`."""

    def check_and_record(self, token_id: str, expires_at: datetime, now: datetime) -> bool:
        raise NotImplementedError("TODO(Hieu): replay state (OD-08)")
