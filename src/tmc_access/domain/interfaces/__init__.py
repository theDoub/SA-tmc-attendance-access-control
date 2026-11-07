"""Ports (abstractions) implemented by outer layers.

Contracts: docs/contracts/edge-access-contracts.md.
"""

from tmc_access.domain.interfaces.access import AccessPolicyEngine
from tmc_access.domain.interfaces.gate import GateAdapter
from tmc_access.domain.interfaces.qr import QrValidator, ReplayGuard
from tmc_access.domain.interfaces.repositories import AttendanceRepository, OutboxRepository
from tmc_access.domain.interfaces.sync import SyncClient

__all__ = [
    "AccessPolicyEngine",
    "AttendanceRepository",
    "GateAdapter",
    "OutboxRepository",
    "QrValidator",
    "ReplayGuard",
    "SyncClient",
]
