"""Turnstile result types (lifecycle stages 3 and 4), deliberately separate.

A1 refs: Fig. 6 (UnlockGate / QueryPassageStatus), LSP bullet ("a command acknowledgement must
never be falsified as physical passage confirmation"), Table 25.
"""

from dataclasses import dataclass
from enum import StrEnum


class GateAck(StrEnum):
    """Result of the unlock COMMAND. Says nothing about whether anyone walked through."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"


class PassageStatus(StrEnum):
    """Result of the passage query. UNAVAILABLE means the hardware cannot report it (OD-05)."""

    CONFIRMED = "CONFIRMED"
    NOT_CONFIRMED = "NOT_CONFIRMED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class GateCommandResult:
    """Unlock acknowledgement only. Intentionally has no passage field."""

    command_id: str
    ack: GateAck
    detail: str | None = None
