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
@pytest.mark.parametrize("direction", list(Direction))
def test_scenario_is_deterministic(name: str, direction: Direction) -> None:
    ack, passage = EXPECTED[name]
    gate = MockTurnstileAdapter(MockScenario.by_name(name))
    for _ in range(3):
        result = gate.unlock("cmd-1", "gate-1", direction, 800)
        assert result.command_id == "cmd-1"
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


@pytest.mark.unit
@pytest.mark.parametrize("field", ["command_id", "gate_id", "direction", "timeout_ms"])
@pytest.mark.parametrize("invalid", [None, "", " ", 0, -1, True, 1.5])
def test_invalid_unlock_does_not_issue_command(field: str, invalid) -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    arguments = dict(command_id="c", gate_id="g", direction=Direction.ENTRY, timeout_ms=800)
    arguments[field] = invalid
    with pytest.raises(GateError, match=field):
        gate.unlock(**arguments)
    assert gate.issued_commands == {}


@pytest.mark.unit
def test_plain_string_direction_is_contract_misuse() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    with pytest.raises(GateError, match="direction"):
        gate.unlock("c", "g", "ENTRY", 800)  # type: ignore[arg-type]
    assert gate.issued_commands == {}


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [None, "", " ", 0, -1, True, 1.5])
def test_invalid_passage_window_preserves_command(invalid) -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    gate.unlock("c", "g", Direction.ENTRY, 800)
    with pytest.raises(GateError, match="window_seconds"):
        gate.query_passage("c", invalid)
    assert gate.query_passage("c", 15) is PassageStatus.CONFIRMED


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [None, "", " ", 123])
def test_invalid_passage_command_id(invalid) -> None:
    gate = MockTurnstileAdapter(MockScenario.timeout())
    with pytest.raises(GateError, match="command_id"):
        gate.query_passage(invalid, 15)


@pytest.mark.unit
def test_command_history_is_a_snapshot() -> None:
    gate = MockTurnstileAdapter(MockScenario.acked_with_passage())
    gate.unlock("c1", "g1", Direction.ENTRY, 800)
    snapshot = gate.issued_commands
    snapshot.clear()
    gate.unlock("c2", "g2", Direction.EXIT, 800)
    assert gate.issued_commands == {
        "c1": ("g1", Direction.ENTRY),
        "c2": ("g2", Direction.EXIT),
    }
    assert gate.query_passage("c1", 15) is PassageStatus.CONFIRMED
    assert gate.query_passage("c2", 15) is PassageStatus.CONFIRMED


@pytest.mark.unit
def test_unknown_passage_status_can_be_scripted_independently() -> None:
    gate = MockTurnstileAdapter(MockScenario(GateAck.ACKNOWLEDGED, PassageStatus.UNKNOWN))
    assert gate.unlock("c", "g", Direction.ENTRY, 800).ack is GateAck.ACKNOWLEDGED
    assert gate.query_passage("c", 15) is PassageStatus.UNKNOWN


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [None, "acked_with_passage"])
def test_invalid_scenario_configuration(invalid) -> None:
    with pytest.raises(ValueError, match="MockScenario"):
        MockTurnstileAdapter(invalid)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ack", "passage"),
    [("ACKNOWLEDGED", PassageStatus.CONFIRMED), (GateAck.ACKNOWLEDGED, "CONFIRMED")],
)
def test_scenario_requires_domain_enums(ack, passage) -> None:
    with pytest.raises(ValueError, match="enum"):
        MockScenario(ack, passage)
