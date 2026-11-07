"""Mock turnstile determinism. Acknowledgement and passage are asserted separately."""

import pytest

from tmc_access.domain.errors import GateError
from tmc_access.domain.models import Direction, GateAck, PassageStatus
from tmc_access.infrastructure.turnstile.mock_turnstile import (
    SCENARIO_NAMES,
    MockScenario,
    MockTurnstileAdapter,
)

EXPECTED = {
    "acked_with_passage": (GateAck.ACKNOWLEDGED, PassageStatus.CONFIRMED),
    "acked_no_passage": (GateAck.ACKNOWLEDGED, PassageStatus.NOT_CONFIRMED),
    "acked_passage_unavailable": (GateAck.ACKNOWLEDGED, PassageStatus.UNAVAILABLE),
    "rejected": (GateAck.REJECTED, PassageStatus.NOT_CONFIRMED),
    "timeout": (GateAck.TIMEOUT, PassageStatus.UNKNOWN),
    "unavailable": (GateAck.UNAVAILABLE, PassageStatus.UNAVAILABLE),
}


@pytest.mark.unit
def test_expected_table_covers_every_scenario() -> None:
    assert set(EXPECTED) == set(SCENARIO_NAMES)


@pytest.mark.unit
@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_scenario_is_deterministic(name: str) -> None:
    ack, passage = EXPECTED[name]
    gate = MockTurnstileAdapter(MockScenario.by_name(name))
    for _ in range(3):
        result = gate.unlock("cmd-1", "gate-1", Direction.ENTRY, 800)
        assert result.ack is ack
        assert gate.query_passage("cmd-1", 15) is passage


@pytest.mark.unit
def test_scenario_argument_is_required() -> None:
    with pytest.raises(TypeError):
        MockTurnstileAdapter()  # type: ignore[call-arg]


@pytest.mark.unit
def test_ack_is_not_passage() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_no_passage())
    assert gate.unlock("c", "g", Direction.EXIT, 800).ack is GateAck.ACKNOWLEDGED
    assert gate.query_passage("c", 15) is not PassageStatus.CONFIRMED


@pytest.mark.unit
def test_unlock_result_has_no_passage_field() -> None:
    result = MockTurnstileAdapter(MockScenario.acked_with_passage()).unlock(
        "c", "g", Direction.ENTRY, 800
    )
    assert not hasattr(result, "passage")


@pytest.mark.unit
def test_unknown_command_raises_gate_error() -> None:
    with pytest.raises(GateError):
        MockTurnstileAdapter(MockScenario.acked_with_passage()).query_passage("nope", 15)


@pytest.mark.unit
def test_inconsistent_scenario_rejected() -> None:
    with pytest.raises(ValueError):
        MockScenario(GateAck.REJECTED, PassageStatus.CONFIRMED)


@pytest.mark.unit
def test_unknown_scenario_name() -> None:
    with pytest.raises(ValueError):
        MockScenario.by_name("always_ok")


@pytest.mark.unit
def test_issued_commands_recorded() -> None:
    gate = MockTurnstileAdapter(MockScenario.rejected())
    gate.unlock("c1", "gate-9", Direction.EXIT, 800)
    assert gate.issued_commands == {"c1": ("gate-9", Direction.EXIT)}
