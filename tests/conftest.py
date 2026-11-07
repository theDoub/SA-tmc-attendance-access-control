"""Shared fixtures. All data is synthetic."""

import pytest

from tmc_access.config.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        edge_id="edge-test",
        station_id="station-test",
        factory_id="factory-test",
        sqlite_path=tmp_path / "edge.db",
        turnstile_mode="mock",
        turnstile_mock_scenario="acked_with_passage",
    )


def pytest_terminal_summary(terminalreporter) -> None:
    skipped = terminalreporter.stats.get("skipped", [])
    pending = [r for r in skipped if "PENDING" in str(r.longrepr)]
    if pending:
        terminalreporter.write_sep(
            "=", f"{len(pending)} PENDING scenarios skipped: functionality NOT implemented yet"
        )
