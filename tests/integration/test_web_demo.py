"""Integration tests for the TMC Factory Gate Control Center web demo."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tmc_access.config.demo_container import create_demo_app


@pytest.fixture()
def demo_client(tmp_path: Path) -> TestClient:
    app = create_demo_app(demo_dir=tmp_path / "demo")
    return TestClient(app)


@pytest.mark.integration
def test_ui_and_health_load(demo_client: TestClient) -> None:
    root = demo_client.get("/")
    assert root.status_code == 200
    assert "TMC Factory Gate Control Center" in root.text

    health = demo_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "demo"}


@pytest.mark.integration
def test_scenario_1_valid_qr_attendance_and_sync(demo_client: TestClient) -> None:
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    scan = demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    ).json()

    assert scan["attempt"]["status"] == "PASSAGE_CONFIRMED"
    assert scan["attendance"]["sync_status"] == "PENDING"
    assert scan["attendance"]["source_sequence"] == 1

    sync = demo_client.post("/demo/sync", json={"mode": "sync"}).json()
    assert sync["ok"] is True
    assert sync["state"]["outbox_counts"]["SYNCED"] == 1
    assert sync["state"]["hub_event_count"] == 1


@pytest.mark.integration
def test_scenario_2_malformed_qr_cannot_unlock(demo_client: TestClient) -> None:
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": True},
    ).json()

    scan = demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    ).json()

    assert scan["attempt"]["status"] == "DENIED"
    assert scan["attempt"]["reason_code"] == "QR_MALFORMED"
    assert scan["attendance"] is None
    assert scan["state"]["attendance_count"] == 0


@pytest.mark.integration
def test_scenario_3_replay_attack_rejected(demo_client: TestClient) -> None:
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    payload = {
        "factory_id": "BINH_DUONG",
        "station_id": "STATION_BD_01",
        "gate_id": "GATE_01",
        "direction": "ENTRY",
        "payload": cred["token"],
        "gate_scenario": "acked_with_passage",
    }
    first = demo_client.post("/demo/scan", json=payload).json()
    second = demo_client.post("/demo/scan", json=payload).json()

    assert first["attempt"]["status"] == "PASSAGE_CONFIRMED"
    assert second["attempt"]["status"] == "DENIED"
    assert second["attempt"]["reason_code"] == "QR_REPLAYED"
    assert second["state"]["attendance_count"] == 1


@pytest.mark.integration
def test_scenario_4_policy_denied_no_attendance(demo_client: TestClient) -> None:
    # emp_002 is only authorized at GATE_02, not GATE_01
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_002", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    scan = demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    ).json()

    assert scan["attempt"]["status"] == "DENIED"
    assert scan["attempt"]["reason_code"] == "NOT_AUTHORIZED_FOR_GATE"
    assert scan["attendance"] is None


@pytest.mark.integration
def test_scenario_5_gate_timeout_no_attendance(demo_client: TestClient) -> None:
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    scan = demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "timeout",
        },
    ).json()

    assert scan["attempt"]["status"] == "UNLOCK_TIMEOUT"
    assert scan["attendance"] is None
    assert scan["state"]["attendance_count"] == 0


@pytest.mark.integration
def test_scenario_6_offline_pending_then_reconnect_synced(demo_client: TestClient) -> None:
    demo_client.post("/demo/connectivity", json={"connected": False})

    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    scan = demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    ).json()
    assert scan["attempt"]["status"] == "PASSAGE_CONFIRMED"

    offline_sync = demo_client.post("/demo/sync", json={"mode": "retry"}).json()
    assert offline_sync["ok"] is False
    assert offline_sync["state"]["outbox_counts"]["PENDING"] == 1
    assert offline_sync["state"]["hub_event_count"] == 0

    demo_client.post("/demo/connectivity", json={"connected": True})
    online_sync = demo_client.post("/demo/sync", json={"mode": "retry"}).json()
    assert online_sync["ok"] is True
    assert online_sync["state"]["outbox_counts"]["SYNCED"] == 1
    assert online_sync["state"]["hub_event_count"] == 1


@pytest.mark.integration
def test_scenario_7_lost_ack_idempotent_retry(demo_client: TestClient) -> None:
    cred = demo_client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()

    demo_client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    )

    demo_client.post("/demo/connectivity", json={"connected": True, "lose_ack_once": True})
    lost = demo_client.post("/demo/sync", json={"mode": "retry"}).json()
    assert lost["ok"] is False
    assert lost["state"]["outbox_counts"]["PENDING"] == 1
    assert lost["state"]["hub_event_count"] == 1

    demo_client.post("/demo/connectivity", json={"connected": True})
    retried = demo_client.post("/demo/sync", json={"mode": "retry"}).json()
    assert retried["ok"] is True
    assert retried["state"]["outbox_counts"]["SYNCED"] == 1
    assert retried["state"]["hub_event_count"] == 1


@pytest.mark.integration
def test_database_viewers_and_isolated_reset(tmp_path: Path) -> None:
    unrelated = tmp_path / "keep_me.txt"
    unrelated.write_text("do-not-delete", encoding="utf-8")

    client = TestClient(create_demo_app(demo_dir=tmp_path / "demo"))
    cred = client.post(
        "/demo/credentials",
        json={"employee_id": "emp_001", "station_id": "STATION_BD_01", "malformed": False},
    ).json()
    client.post(
        "/demo/scan",
        json={
            "factory_id": "BINH_DUONG",
            "station_id": "STATION_BD_01",
            "gate_id": "GATE_01",
            "direction": "ENTRY",
            "payload": cred["token"],
            "gate_scenario": "acked_with_passage",
        },
    )

    assert len(client.get("/demo/attempts").json()) == 1
    assert len(client.get("/demo/attendance").json()) == 1
    assert len(client.get("/demo/outbox").json()) == 1

    reset_state = client.post("/demo/reset").json()
    assert reset_state["attempt_count"] == 0
    assert reset_state["attendance_count"] == 0
    assert reset_state["hub_event_count"] == 0
    assert unrelated.exists()
