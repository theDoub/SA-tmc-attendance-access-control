from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tmc_access.config.container import build_container
from tmc_access.domain.models import AccessAttempt, AttemptStatus, ScanInput
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
def test_scan_processes_request_without_echoing_payload(client) -> None:
    body = {
        "request_id": "r1",
        "station_id": "s1",
        "gate_id": "g1",
        "direction": "ENTRY",
        "payload": "synthetic-payload",
    }
    response = client.post("/scan", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "DENIED"
    assert response.json()["reason_code"] == "QR_MALFORMED"
    assert "synthetic-payload" not in response.text


@pytest.mark.unit
def test_scan_input_repr_redacts_payload() -> None:
    from tmc_access.domain.models import Direction

    scan = ScanInput("r", "s", "g", Direction.ENTRY, datetime.now(UTC), "secret-qr-value")
    assert "secret-qr-value" not in repr(scan)


@pytest.mark.unit
def test_scan_returns_attempt_status_without_echoing_payload() -> None:
    class DenyingCoordinator:
        def handle_scan(self, scan: ScanInput) -> AccessAttempt:
            return AccessAttempt(
                access_attempt_id=scan.request_id,
                station_id=scan.station_id,
                gate_id=scan.gate_id,
                direction=scan.direction,
                received_at=scan.received_at,
                status=AttemptStatus.DENIED,
                reason_code="POLICY_MISSING",
            )

    client = TestClient(create_app(DenyingCoordinator()))  # type: ignore[arg-type]
    response = client.post(
        "/scan",
        json={
            "request_id": "r1",
            "station_id": "s1",
            "gate_id": "g1",
            "direction": "ENTRY",
            "payload": "secret-qr-value",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_attempt_id": "r1",
        "status": "DENIED",
        "reason_code": "POLICY_MISSING",
    }
    assert "secret-qr-value" not in response.text
