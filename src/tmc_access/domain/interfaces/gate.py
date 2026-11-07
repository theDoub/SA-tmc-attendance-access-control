"""Turnstile port. Owner: Bui Doan Minh Nhat (adapters); contract reviewed by Nguyen Ngoc Kim."""

from typing import Protocol

from tmc_access.domain.models import Direction, GateCommandResult, PassageStatus


class GateAdapter(Protocol):
    """A1 Fig. 6 `ITurnstileAdapter`: command acknowledgement and passage are separate calls."""

    def unlock(
        self, command_id: str, gate_id: str, direction: Direction, timeout_ms: int
    ) -> GateCommandResult:
        """Request opening. Must return within `timeout_ms` (A1: 800 ms budget).

        Returns ACKNOWLEDGED / REJECTED / TIMEOUT / UNAVAILABLE. An acknowledgement MUST NOT
        be presented as passage (A1 LSP bullet). TIMEOUT means the outcome is uncertain.

        Raises:
            GateError: contract misuse or unexpected adapter failure.
        """
        ...

    def query_passage(self, command_id: str, window_seconds: int) -> PassageStatus:
        """Report whether passage was observed for a previously issued command.

        UNAVAILABLE if the hardware does not expose passage sensing (OD-05).

        Raises:
            GateError: unknown `command_id` or adapter failure.
        """
        ...
