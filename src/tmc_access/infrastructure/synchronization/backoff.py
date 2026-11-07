"""Retry/backoff configuration holder (A1 section 4.3.5). Data only; no scheduling logic.

Lives in infrastructure (not domain) because retry timing is an operational concern.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffConfig:
    delays_seconds: tuple[float, ...] = (5, 10, 20, 40, 60)
    jitter_min: float = 0.8
    jitter_max: float = 1.0

    def __post_init__(self) -> None:
        if not self.delays_seconds or any(d <= 0 for d in self.delays_seconds):
            raise ValueError("delays_seconds must be non-empty and positive")
        if not 0 < self.jitter_min <= self.jitter_max:
            raise ValueError("require 0 < jitter_min <= jitter_max")
