"""Vendor turnstile adapter placeholder. TODO(Nhat). The vendor API is not specified (OD-13)."""

from tmc_access.domain.models import Direction, GateCommandResult, PassageStatus


class VendorTurnstileAdapter:
    """Satisfies `GateAdapter`."""

    def unlock(
        self, command_id: str, gate_id: str, direction: Direction, timeout_ms: int
    ) -> GateCommandResult:
        raise NotImplementedError("TODO(Nhat): vendor turnstile API is unspecified (OD-13)")

    def query_passage(self, command_id: str, window_seconds: int) -> PassageStatus:
        raise NotImplementedError("TODO(Nhat): vendor turnstile API is unspecified (OD-13)")
