"""Operational retry scheduling, separate from access decisions and domain models."""

from collections.abc import Callable
from random import uniform
from threading import Event, Lock
from time import monotonic
from typing import Protocol

from tmc_access.domain.errors import StorageError, SyncError
from tmc_access.infrastructure.synchronization.backoff import BackoffConfig


class SyncOperation(Protocol):
    def sync_once(self) -> None: ...


class SyncRetryWorker:
    """tick is non-sleeping; run is an optional, explicitly started background loop.

    Schedule state is process-local. After restart persisted pending events are
    retried immediately; the backoff counter starts again. No gate operation runs here.
    """

    def __init__(
        self,
        service: SyncOperation,
        backoff: BackoffConfig,
        clock: Callable[[], float] = monotonic,
        random_uniform: Callable[[float, float], float] = uniform,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._service = service
        self._backoff = backoff
        self._clock = clock
        self._random = random_uniform
        self._poll_seconds = poll_seconds
        self._lock = Lock()
        self.failures = 0
        self.next_attempt_at = clock()
        self.last_error: str | None = None

    def tick(self) -> bool:
        """Attempt one due batch. False means waiting; no sleep or gate dependency."""
        with self._lock:
            if self._clock() < self.next_attempt_at:
                return False
            try:
                self._service.sync_once()
            except (SyncError, StorageError) as exc:
                index = min(self.failures, len(self._backoff.delays_seconds) - 1)
                jitter = self._random(self._backoff.jitter_min, self._backoff.jitter_max)
                if not self._backoff.jitter_min <= jitter <= self._backoff.jitter_max:
                    raise ValueError(
                        "random source returned jitter outside configured range"
                    ) from exc
                self.failures += 1
                self.next_attempt_at = self._clock() + self._backoff.delays_seconds[index] * jitter
                self.last_error = type(exc).__name__  # Never log payloads or error contents.
            else:
                self.failures = 0
                self.last_error = None
                self.next_attempt_at = self._clock() + self._poll_seconds
            return True

    def run(self, stop: Event) -> None:
        """Run in a dedicated thread; stop.wait makes shutdown interruptible."""
        while not stop.is_set():
            self.tick()
            stop.wait(max(0.001, self.next_attempt_at - self._clock()))
