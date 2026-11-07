from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tmc_access.config.container import build_container
from tmc_access.presentation.api.app import create_app


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(build_container(settings).coordinator))


@pytest.mark.unit
def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "scaffold-only"


@pytest.mark.unit
def test_scan_reports_not_implemented(client) -> None:
    body = {
        "request_id": "r1",
        "station_id": "s1",
        "gate_id": "g1",
        "direction": "ENTRY",
        "payload": "synthetic-payload",
    }
    response = client.post("/scan", json=body)
    assert response.status_code == 501
    assert "synthetic-payload" not in response.text


@pytest.mark.unit
def test_scan_input_repr_redacts_payload() -> None:
    from tmc_access.domain.models import Direction, ScanInput

    scan = ScanInput("r", "s", "g", Direction.ENTRY, datetime.now(UTC), "secret-qr-value")
    assert "secret-qr-value" not in repr(scan)
