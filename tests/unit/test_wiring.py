import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest

from tmc_access.config.container import build_container, build_gate
from tmc_access.config.settings import Settings
from tmc_access.domain.models import Direction, ScanInput
from tmc_access.infrastructure.turnstile.mock_turnstile import SCENARIO_NAMES, MockScenario


@pytest.mark.unit
def test_container_wires_coordinator_and_sync(settings) -> None:
    container = build_container(settings)
    assert container.coordinator is not None
    assert container.sync_service is not None
    assert settings.sqlite_path.is_file()
    with closing(sqlite3.connect(settings.sqlite_path)) as conn:
        assert conn.execute("SELECT count(*) FROM access_attempts").fetchone()[0] == 0


@pytest.mark.unit
def test_coordinator_handles_scan_and_empty_outbox_has_nothing_to_sync(settings) -> None:
    container = build_container(settings)
    scan = ScanInput("r1", "s1", "g1", Direction.ENTRY, datetime.now(UTC), "synthetic-payload")
    attempt = container.coordinator.handle_scan(scan)
    assert attempt.status.value == "DENIED"
    container.sync_service.sync_once()  # Empty batch must not contact even a stub client.


@pytest.mark.unit
def test_mock_mode_requires_explicit_scenario(tmp_path) -> None:
    bad = Settings(
        _env_file=None,
        edge_id="e",
        station_id="s",
        factory_id="f",
        sqlite_path=tmp_path / "x.db",
        turnstile_mode="mock",
    )
    with pytest.raises(ValueError, match="MOCK_SCENARIO"):
        build_container(bad)


@pytest.mark.unit
@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_mock_scenario_is_wired_from_settings(settings, name: str) -> None:
    configured = settings.model_copy(
        update={"turnstile_mode": "mock", "turnstile_mock_scenario": name}
    )
    gate = build_gate(configured)
    expected = MockScenario.by_name(name)
    result = gate.unlock("synthetic-command", "synthetic-gate", Direction.ENTRY, 800)
    assert result.ack is expected.ack
    assert gate.query_passage(result.command_id, 15) is expected.passage


@pytest.mark.unit
def test_settings_defaults_match_a1(settings) -> None:
    assert settings.cache_fresh_seconds == 300
    assert settings.cache_max_stale_seconds == 7200
    assert settings.central_auth_timeout_ms == 500
    assert settings.turnstile_timeout_ms == 800
    assert settings.passage_window_seconds == 15
    assert settings.sync_backoff_delays_seconds == (5, 10, 20, 40, 60)
    assert (settings.sync_backoff_jitter_min, settings.sync_backoff_jitter_max) == (0.8, 1.0)
    assert settings.qr_clock_skew_seconds is None


@pytest.mark.unit
def test_backoff_config_flows_from_settings(settings) -> None:
    assert build_container(settings).backoff.delays_seconds == (5, 10, 20, 40, 60)
