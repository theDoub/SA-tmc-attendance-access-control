"""Local access-policy snapshot types used by the Edge policy engine.

Policy distribution is outside this module.  These immutable types describe the active
snapshot after it has been loaded by an outer-layer provider.
"""

from dataclasses import dataclass
from datetime import datetime

from tmc_access.domain.models.access import Direction


@dataclass(frozen=True)
class AccessGrant:
    """Permission to use one gate in one direction during an optional time window."""

    gate_id: str
    direction: Direction
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not self.gate_id:
            raise ValueError("gate_id must not be empty")
        for field_name, value in (
            ("valid_from", self.valid_from),
            ("valid_until", self.valid_until),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("valid_until must be later than valid_from")

    def is_active_at(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ValueError("grant evaluation time must be timezone-aware")
        if self.valid_from is not None and now < self.valid_from:
            return False
        return self.valid_until is None or now < self.valid_until


@dataclass(frozen=True)
class SubjectPolicy:
    """Active state and gate grants for one opaque employee subject."""

    subject_id: str
    active: bool
    grants: frozenset[AccessGrant] = frozenset()

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise ValueError("subject_id must not be empty")

    def allows(self, gate_id: str, direction: Direction, now: datetime) -> bool:
        return any(
            grant.gate_id == gate_id and grant.direction is direction and grant.is_active_at(now)
            for grant in self.grants
        )


@dataclass(frozen=True)
class PolicySnapshot:
    """Versioned local policy snapshot and the time it was last refreshed."""

    version: str
    refreshed_at: datetime
    subjects: tuple[SubjectPolicy, ...]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("policy version must not be empty")
        if self.refreshed_at.tzinfo is None:
            raise ValueError("refreshed_at must be timezone-aware")
        subject_ids = [subject.subject_id for subject in self.subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("policy snapshot contains duplicate subject ids")

    def policy_for(self, subject_id: str) -> SubjectPolicy | None:
        return next((item for item in self.subjects if item.subject_id == subject_id), None)
