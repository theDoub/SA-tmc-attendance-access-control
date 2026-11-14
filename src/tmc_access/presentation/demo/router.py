"""FastAPI router and app factory for the TMC Factory Gate Control Center demo."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tmc_access.presentation.demo.contracts import (
    ConnectivityRequest,
    CredentialIssueRequest,
    DemoRuntimePort,
    DemoScanRequest,
    SyncTriggerRequest,
)

STATIC_DIR = Path(__file__).parent / "static"


def create_demo_router(runtime: DemoRuntimePort) -> APIRouter:
    """Create API routes backed by a `DemoRuntimePort` implementation."""
    router = APIRouter()

    @router.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "demo"}

    @router.get("/demo/state")
    def get_state() -> dict[str, Any]:
        return runtime.get_state()

    @router.post("/demo/credentials")
    def issue_credential(body: CredentialIssueRequest) -> dict[str, Any]:
        try:
            return runtime.issue_credential(
                employee_id=body.employee_id,
                station_id=body.station_id,
                malformed=body.malformed,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/demo/scan")
    def scan(body: DemoScanRequest) -> dict[str, Any]:
        try:
            return runtime.scan(
                factory_id=body.factory_id,
                station_id=body.station_id,
                gate_id=body.gate_id,
                direction=body.direction,
                payload=body.payload,
                gate_scenario=body.gate_scenario,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/demo/connectivity")
    def set_connectivity(body: ConnectivityRequest) -> dict[str, Any]:
        try:
            return runtime.set_connectivity(
                connected=body.connected,
                lose_ack_once=body.lose_ack_once,
                gate_scenario=body.gate_scenario,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/demo/sync")
    def trigger_sync(body: SyncTriggerRequest) -> dict[str, Any]:
        return runtime.trigger_sync(mode=body.mode)

    @router.get("/demo/attempts")
    def get_attempts(limit: int = 50) -> list[dict[str, Any]]:
        return runtime.get_attempts(limit=limit)

    @router.get("/demo/attendance")
    def get_attendance(limit: int = 50) -> list[dict[str, Any]]:
        return runtime.get_attendance(limit=limit)

    @router.get("/demo/outbox")
    def get_outbox(limit: int = 50) -> list[dict[str, Any]]:
        return runtime.get_outbox(limit=limit)

    @router.post("/demo/reset")
    def reset_demo() -> dict[str, Any]:
        return runtime.reset()

    return router


def create_demo_app_from_runtime(runtime: DemoRuntimePort) -> FastAPI:
    """Build the FastAPI application with demo routes and static UI assets."""
    app = FastAPI(title="TMC Factory Gate Control Center (Demo)")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="demo-static")
    app.include_router(create_demo_router(runtime))
    return app
