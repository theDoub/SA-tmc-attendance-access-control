"""Composition root: builds the object graph from settings."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from random import uniform
from time import monotonic

from fastapi import FastAPI

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.application.synchronization.sync_service import SyncService
from tmc_access.config.settings import Settings
from tmc_access.domain.interfaces import (
    AttendanceRepository,
    GateAdapter,
    OutboxRepository,
    SyncClient,
)
from tmc_access.domain.policies.evaluator import AccessPolicyEvaluator
from tmc_access.infrastructure.persistence.sqlite import (
    SqliteAttendanceRepository,
    SqliteOutboxRepository,
)
from tmc_access.infrastructure.qr.public_key_validator import PublicKeyQrValidator
from tmc_access.infrastructure.synchronization.backoff import BackoffConfig
from tmc_access.infrastructure.synchronization.http_client import HttpSyncClient
from tmc_access.infrastructure.synchronization.simulation import (
    SimulatedHubReceiver,
    SimulatedSyncClient,
)
from tmc_access.infrastructure.synchronization.worker import SyncRetryWorker
from tmc_access.infrastructure.turnstile.mock_turnstile import MockScenario, MockTurnstileAdapter
from tmc_access.infrastructure.turnstile.vendor_adapter import VendorTurnstileAdapter
from tmc_access.presentation.api.app import create_app


@dataclass(frozen=True)
class Container:
    settings: Settings
    coordinator: AccessCoordinator
    sync_service: SyncService
    gate: GateAdapter
    backoff: BackoffConfig
    attendance_repository: AttendanceRepository
    outbox_repository: OutboxRepository
    sync_worker: SyncRetryWorker
    simulation_client: SimulatedSyncClient | None
    simulation_receiver: SimulatedHubReceiver | None


def build_gate(settings: Settings) -> GateAdapter:
    if settings.turnstile_mode == "mock":
        if not settings.turnstile_mock_scenario:
            raise ValueError("TMC_TURNSTILE_MOCK_SCENARIO is required when TMC_TURNSTILE_MODE=mock")
        return MockTurnstileAdapter(MockScenario.by_name(settings.turnstile_mock_scenario))
    return VendorTurnstileAdapter()


def build_container(
    settings: Settings,
    *,
    clock: Callable[[], float] = monotonic,
    random_uniform: Callable[[float, float], float] = uniform,
) -> Container:
    gate = build_gate(settings)
    attendance_repo = SqliteAttendanceRepository(settings.sqlite_path)
    coordinator = AccessCoordinator(
        validator=PublicKeyQrValidator(),
        policy_engine=AccessPolicyEvaluator(
            None,
            fresh_for=timedelta(seconds=settings.cache_fresh_seconds),
            max_stale_for=timedelta(seconds=settings.cache_max_stale_seconds),
        ),
        gate=gate,
        attendance_repository=attendance_repo,
        factory_id=settings.factory_id,
        turnstile_timeout_ms=settings.turnstile_timeout_ms,
        passage_window_seconds=settings.passage_window_seconds,
        sequence_factory=attendance_repo.next_sequence,
    )
    outbox = SqliteOutboxRepository(settings.sqlite_path)
    receiver = None
    simulated_client = None
    client: SyncClient
    if settings.sync_mode == "simulation":
        receiver_path = settings.sync_simulation_db_path or settings.sqlite_path.with_name(
            "simulated-hub.db"
        )
        if receiver_path.resolve() == settings.sqlite_path.resolve():
            raise ValueError("Simulated receiver must use a separate database")
        receiver = SimulatedHubReceiver(receiver_path)
        simulated_client = SimulatedSyncClient(receiver)
        client = simulated_client
    else:
        client = HttpSyncClient(settings.hub_base_url)
    sync_service = SyncService(outbox=outbox, client=client)
    backoff = BackoffConfig(
        delays_seconds=settings.sync_backoff_delays_seconds,
        jitter_min=settings.sync_backoff_jitter_min,
        jitter_max=settings.sync_backoff_jitter_max,
    )
    worker = SyncRetryWorker(sync_service, backoff, clock=clock, random_uniform=random_uniform)
    return Container(
        settings,
        coordinator,
        sync_service,
        gate,
        backoff,
        attendance_repo,
        outbox,
        worker,
        simulated_client,
        receiver,
    )


def create_default_app() -> FastAPI:
    """Uvicorn factory: `uvicorn tmc_access.config.container:create_default_app --factory`."""
    return create_app(build_container(Settings()).coordinator)  # type: ignore[call-arg]
