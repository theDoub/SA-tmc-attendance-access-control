"""Gate access coordinator skeleton. Owner: Nguyen Ngoc Kim.

Depends only on domain abstractions (DIP). Intended flow, PROPOSED and pending team
confirmation (OD-04, OD-05): validate QR -> evaluate policy -> persist attempt -> unlock ->
query passage -> persist AttendanceRecord + outbox atomically.
"""

from tmc_access.domain.interfaces import (
    AccessPolicyEngine,
    AttendanceRepository,
    GateAdapter,
    QrValidator,
)
from tmc_access.domain.models import AccessAttempt, ScanInput


class AccessCoordinator:
    def __init__(
        self,
        validator: QrValidator,
        policy_engine: AccessPolicyEngine,
        gate: GateAdapter,
        attendance_repository: AttendanceRepository,
    ) -> None:
        self._validator = validator
        self._policy_engine = policy_engine
        self._gate = gate
        self._attendance_repository = attendance_repository

    def handle_scan(self, scan: ScanInput) -> AccessAttempt:
        raise NotImplementedError("TODO(Kim): access decision flow")
