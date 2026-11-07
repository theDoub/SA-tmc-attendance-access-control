"""QR validation ports. Owner: Nguyen Nhat Hieu.

Boundaries (A1 ADR-002, section 3.5.4; unresolved items: OD-01, OD-02, OD-08):
- Verification uses PUBLIC keys only. No signing or issuing capability exists on the Edge.
- The validator owns the *verdict*; the ReplayGuard owns the *replay state*.
"""

from datetime import datetime
from typing import Protocol

from tmc_access.domain.models import QrValidationResult


class ReplayGuard(Protocol):
    """Remembers token ids until their expiry. Persistence strategy is OD-08."""

    def check_and_record(self, token_id: str, expires_at: datetime, now: datetime) -> bool:
        """Atomically record `token_id`; return True if first use, False if already seen.

        Raises:
            StorageError: if replay state cannot be read or written. Callers must then
                fail closed (do not treat the credential as fresh).
        """
        ...


class QrValidator(Protocol):
    """A1 contract `validateQR`."""

    def validate(self, raw_payload: str, station_id: str, now: datetime) -> QrValidationResult:
        """Verify format, signature, audience, expiry, key status and replay state.

        Returns a result for every *expected* rejection (invalid, expired, replayed,
        malformed, ...). Never accepts unverifiable input.

        Raises:
            QrError: infrastructure-level failure (e.g. key store unreadable).
            StorageError: replay state unavailable.
        """
        ...
