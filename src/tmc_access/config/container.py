"""Composition root: builds the object graph from settings."""

from dataclasses import dataclass
from datetime import timedelta

from fastapi import FastAPI

from tmc_access.application.access.coordinator import AccessCoordinator
from tmc_access.application.synchronization.sync_service import SyncService
from tmc_access.config.settings import Settings
from tmc_access.domain.interfaces import GateAdapter
from tmc_access.domain.policies.evaluator import AccessPolicyEvaluator
from tmc_access.infrastructure.persistence.sqlite import (
    SqliteAttendanceRepository,
    SqliteOutboxRepository,
)
from tmc_access.infrastructure.qr.public_key_validator import PublicKeyQrValidator
from tmc_access.infrastructure.synchronization.backoff import BackoffConfig
from tmc_access.infrastructure.synchronization.http_client import HttpSyncClient
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


def build_gate(settings: Settings) -> GateAdapter:
    if settings.turnstile_mode == "mock":
        if not settings.turnstile_mock_scenario:
            raise ValueError("TMC_TURNSTILE_MOCK_SCENARIO is required when TMC_TURNSTILE_MODE=mock")
        return MockTurnstileAdapter(MockScenario.by_name(settings.turnstile_mock_scenario))
    return VendorTurnstileAdapter()


def build_container(settings: Settings) -> Container:
    gate = build_gate(settings)
    attendance_repo = SqliteAttendanceRepository()
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
    )
    sync_service = SyncService(
        outbox=SqliteOutboxRepository(), client=HttpSyncClient(settings.hub_base_url)
    )
    backoff = BackoffConfig(
        delays_seconds=settings.sync_backoff_delays_seconds,
        jitter_min=settings.sync_backoff_jitter_min,
        jitter_max=settings.sync_backoff_jitter_max,
    )
    return Container(settings, coordinator, sync_service, gate, backoff)


def create_default_app() -> FastAPI:
    """Uvicorn factory: `uvicorn tmc_access.config.container:create_default_app --factory`."""
    return create_app(build_container(Settings()).coordinator)  # type: ignore[call-arg]
