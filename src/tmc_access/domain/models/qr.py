"""QR validation result types (lifecycle stage 1). Public-key verification only.

A1 refs: ADR-002, section 3.5.4, Table 16 (validateQR). Payload claim set is OD-02.
The raw QR payload is never stored in these types (A1 Table 15: process, validate, discard).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class QrValidationOutcome(StrEnum):
    VALID = "VALID"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    EXPIRED = "EXPIRED"
    REPLAYED = "REPLAYED"
    MALFORMED = "MALFORMED"
    WRONG_AUDIENCE = "WRONG_AUDIENCE"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    CLOCK_UNRELIABLE = "CLOCK_UNRELIABLE"


@dataclass(frozen=True)
class VerifiedCredential:
    """Claims that survived verification. `subject_id` is an opaque employee reference (OD-02)."""

    subject_id: str
    token_id: str
    key_version: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class QrValidationResult:
    """Outcome of validation. A credential is present if and only if the outcome is VALID."""

    outcome: QrValidationOutcome
    credential: VerifiedCredential | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        is_valid = self.outcome is QrValidationOutcome.VALID
        if is_valid and self.credential is None:
            raise ValueError("VALID result requires a verified credential")
        if not is_valid and self.credential is not None:
            raise ValueError("Non-VALID result must not carry a credential")

    @property
    def is_valid(self) -> bool:
        return self.outcome is QrValidationOutcome.VALID
