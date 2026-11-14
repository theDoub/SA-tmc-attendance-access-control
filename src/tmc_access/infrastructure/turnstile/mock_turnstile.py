"""Deterministic mock turnstile for tests and local simulation. No hardware required.

Outcomes are scripted explicitly via `MockScenario`; there is no default and no
unconditional success. Command acknowledgement and passage are scripted separately, and
`unlock` never reports passage.
"""

from dataclasses import dataclass

from tmc_access.domain.errors import GateError
from tmc_access.domain.models import Direction, GateAck, GateCommandResult, PassageStatus


@dataclass(frozen=True)
class MockScenario:
    ack: GateAck
    passage: PassageStatus

    def __post_init__(self) -> None:
        if not isinstance(self.ack, GateAck) or not isinstance(self.passage, PassageStatus):
            raise ValueError("Scenario requires GateAck and PassageStatus enum values")
        no_open = {GateAck.REJECTED, GateAck.UNAVAILABLE}
        if self.ack in no_open and self.passage not in {
            PassageStatus.NOT_CONFIRMED,
            PassageStatus.UNAVAILABLE,
        }:
            raise ValueError(f"A gate command that was {self.ack} cannot yield passage evidence")

    @classmethod
    def acked_with_passage(cls) -> "MockScenario":
        return cls(GateAck.ACKNOWLEDGED, PassageStatus.CONFIRMED)

    @classmethod
    def acked_no_passage(cls) -> "MockScenario":
        return cls(GateAck.ACKNOWLEDGED, PassageStatus.NOT_CONFIRMED)

    @classmethod
    def acked_passage_unavailable(cls) -> "MockScenario":
        return cls(GateAck.ACKNOWLEDGED, PassageStatus.UNAVAILABLE)

    @classmethod
    def rejected(cls) -> "MockScenario":
        return cls(GateAck.REJECTED, PassageStatus.NOT_CONFIRMED)

    @classmethod
    def timeout(cls) -> "MockScenario":
        """Uncertain outcome: command result unknown, passage not knowable (A1 Table 26)."""
        return cls(GateAck.TIMEOUT, PassageStatus.UNKNOWN)

    @classmethod
    def unavailable(cls) -> "MockScenario":
        return cls(GateAck.UNAVAILABLE, PassageStatus.UNAVAILABLE)

    @classmethod
    def by_name(cls, name: str) -> "MockScenario":
        factory = getattr(cls, name, None)
        if name not in SCENARIO_NAMES or factory is None:
            raise ValueError(f"Unknown mock scenario {name!r}; expected one of {SCENARIO_NAMES}")
        return factory()


SCENARIO_NAMES = (
    "acked_with_passage",
    "acked_no_passage",
    "acked_passage_unavailable",
    "rejected",
    "timeout",
    "unavailable",
)


class MockTurnstileAdapter:
    """Satisfies `GateAdapter` with immediate, scripted results, without sleeping.

    Timeout and passage-window arguments are validated, not simulated by elapsed
    wall time. TIMEOUT is an explicitly scripted uncertain result. No hardware
    action, retry, attendance creation or persistence is performed by this mock.
    """

    def __init__(self, scenario: MockScenario) -> None:
        if not isinstance(scenario, MockScenario):
            raise ValueError("An explicit MockScenario is required")
        self._scenario = scenario
        self._issued: dict[str, tuple[str, Direction]] = {}

    @property
    def issued_commands(self) -> dict[str, tuple[str, Direction]]:
        """command_id -> (gate_id, direction), for test assertions."""
        return dict(self._issued)

    def unlock(
        self, command_id: str, gate_id: str, direction: Direction, timeout_ms: int
    ) -> GateCommandResult:
        self._require_identifier(command_id, "command_id")
        self._require_identifier(gate_id, "gate_id")
        if not isinstance(direction, Direction):
            raise GateError("direction must be a Direction enum value")
        self._require_positive_integer(timeout_ms, "timeout_ms")
        self._issued[command_id] = (gate_id, direction)
        return GateCommandResult(command_id=command_id, ack=self._scenario.ack, detail="mock")

    def query_passage(self, command_id: str, window_seconds: int) -> PassageStatus:
        self._require_identifier(command_id, "command_id")
        self._require_positive_integer(window_seconds, "window_seconds")
        if command_id not in self._issued:
            raise GateError(f"Unknown command_id {command_id!r}")
        return self._scenario.passage

    @staticmethod
    def _require_identifier(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise GateError(f"{name} must be a non-empty string")

    @staticmethod
    def _require_positive_integer(value: int, name: str) -> None:
        if type(value) is not int or value <= 0:
            raise GateError(f"{name} must be a positive integer")
