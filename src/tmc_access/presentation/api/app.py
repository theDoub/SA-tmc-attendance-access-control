"""FastAPI app: health check and a scan endpoint that reports NOT IMPLEMENTED (HTTP 501)."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.domain.models import Direction, ScanInput


class ScanRequest(BaseModel):
    request_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    gate_id: str = Field(min_length=1)
    direction: Direction
    payload: str = Field(min_length=1, repr=False)


def create_app(coordinator: AccessCoordinator) -> FastAPI:
    app = FastAPI(title="TMC Edge Gate Access (scaffold)")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "scaffold-only"}

    @app.post("/scan")
    def scan(body: ScanRequest) -> JSONResponse:
        scan_input = ScanInput(
            request_id=body.request_id,
            station_id=body.station_id,
            gate_id=body.gate_id,
            direction=body.direction,
            received_at=datetime.now(UTC),
            payload=body.payload,
        )
        try:
            attempt = coordinator.handle_scan(scan_input)
        except NotImplementedError as exc:
            return JSONResponse(status_code=501, content={"detail": f"Not implemented: {exc}"})
        return JSONResponse(
            status_code=200, content={"access_attempt_id": attempt.access_attempt_id}
        )

    return app
