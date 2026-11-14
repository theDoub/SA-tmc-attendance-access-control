"""Presentation-layer contracts for the TMC Factory Gate Control Center demo."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from tmc_access.domain.models import Direction


class DemoRuntimePort(Protocol):
    """Port implemented by the demo composition root (`config.demo_container`)."""

    def get_state(self) -> dict[str, Any]: ...

    def issue_credential(
        self, employee_id: str, station_id: str, malformed: bool
    ) -> dict[str, Any]: ...

    def scan(
        self,
        *,
        factory_id: str,
        station_id: str,
        gate_id: str,
        direction: Direction,
        payload: str,
        gate_scenario: str,
    ) -> dict[str, Any]: ...

    def set_connectivity(
        self,
        *,
        connected: bool | None = None,
        lose_ack_once: bool | None = None,
        gate_scenario: str | None = None,
    ) -> dict[str, Any]: ...

    def trigger_sync(self, *, mode: str = "sync") -> dict[str, Any]: ...

    def get_attempts(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def get_attendance(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def get_outbox(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def reset(self) -> dict[str, Any]: ...


class CredentialIssueRequest(BaseModel):
    employee_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    malformed: bool = False


class DemoScanRequest(BaseModel):
    factory_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    gate_id: str = Field(min_length=1)
    direction: Direction
    payload: str = Field(min_length=1, repr=False)
    gate_scenario: str = Field(default="acked_with_passage", min_length=1)


class ConnectivityRequest(BaseModel):
    connected: bool | None = None
    lose_ack_once: bool | None = None
    gate_scenario: str | None = None


class SyncTriggerRequest(BaseModel):
    mode: str = Field(default="sync", pattern="^(sync|retry)$")
