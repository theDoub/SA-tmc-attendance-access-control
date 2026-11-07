"""QR validator placeholder. TODO(Hieu). Token format and issuance are undecided (OD-01, OD-02).

Verification must use public keys only. This stub never returns VALID.
"""

from datetime import datetime

from tmc_access.domain.models import QrValidationResult


class PublicKeyQrValidator:
    """Satisfies `QrValidator`."""

    def validate(self, raw_payload: str, station_id: str, now: datetime) -> QrValidationResult:
        raise NotImplementedError("TODO(Hieu): signature, expiry, audience and replay checks")
