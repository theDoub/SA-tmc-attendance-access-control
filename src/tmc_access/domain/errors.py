"""Error categories. Kept separate so callers never conflate failure kinds (A1 Table 17)."""


class DomainError(Exception):
    """Base for all categorized domain errors."""


class QrError(DomainError):
    """QR could not be processed (distinct from a normal invalid-QR *result*)."""


class PolicyError(DomainError):
    """Policy data could not be evaluated (missing, corrupt). A policy DENY is a result."""


class GateError(DomainError):
    """Turnstile adapter failure (protocol misuse, unknown command)."""


class StorageError(DomainError):
    """Local persistence failure. Callers must not claim durable success."""


class SyncError(DomainError):
    """Edge-to-Hub synchronization failure."""
