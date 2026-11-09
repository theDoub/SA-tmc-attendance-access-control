"""Environment-driven settings (prefix `TMC_`). Defaults tagged A1 come from Assignment 1.

Operational values (cache windows, timeouts, retry/backoff) live here and in infrastructure,
never in the domain layer. Only dummy values may be committed; see `.env.example`.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TMC_", env_file=".env", extra="ignore")

    # Edge identity (required, no defaults on purpose)
    edge_id: str
    station_id: str
    factory_id: str

    sqlite_path: Path = Path("data/edge.db")
    hub_base_url: str = "https://hub.example.invalid"
    sync_mode: Literal["http", "simulation"] = "http"
    sync_simulation_db_path: Path | None = None

    # QR verification (public keys only). Clock skew has no A1 value: unset (OD-02/OD-08).
    qr_public_key_dir: Path = Path("keys/public")
    qr_clock_skew_seconds: int | None = None

    # A1 Table 28
    cache_fresh_seconds: int = 300
    cache_max_stale_seconds: int = 7200
    central_auth_timeout_ms: int = 500

    # A1 Table 29 and section 4.2.3
    turnstile_timeout_ms: int = 800
    passage_window_seconds: int = 15
    turnstile_mode: Literal["vendor", "mock"] = "vendor"
    turnstile_mock_scenario: str | None = None

    # A1 section 4.3.5
    sync_backoff_delays_seconds: tuple[float, ...] = (5, 10, 20, 40, 60)
    sync_backoff_jitter_min: float = 0.8
    sync_backoff_jitter_max: float = 1.0
