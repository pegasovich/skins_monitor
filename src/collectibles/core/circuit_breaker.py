"""Stateful per-source Circuit Breaker pattern implementation."""

import asyncio
import time
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class CircuitState(StrEnum):
    """Lifecycle states of the Circuit Breaker."""

    CLOSED = "closed"  # Healthy, requests pass through
    OPEN = "open"  # Tripped, requests fail immediately
    HALF_OPEN = "half_open"  # Trial mode, testing provider recovery


class CircuitOpenError(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""


class CircuitBreaker:
    """Protects external adapters and connection pools from cascading failures."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._successful_probes: int = 0
        self._tripped_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current state with automatic transition to HALF_OPEN when timeout expires."""
        if self._state == CircuitState.OPEN:
            now = time.monotonic()
            if (now - self._tripped_at) >= self.recovery_timeout_seconds:
                logger.info(
                    "circuit_breaker.transition_to_half_open",
                    breaker=self.name,
                    elapsed_seconds=round(now - self._tripped_at, 2),
                )
                self._state = CircuitState.HALF_OPEN
                self._successful_probes = 0
        return self._state

    async def record_success(self) -> None:
        """Record successful execution of downstream call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._successful_probes += 1
                logger.debug(
                    "circuit_breaker.probe_success",
                    breaker=self.name,
                    probes=self._successful_probes,
                    threshold=self.half_open_success_threshold,
                )
                if self._successful_probes >= self.half_open_success_threshold:
                    self._state = CircuitState.CLOSED
                    self._consecutive_failures = 0
                    self._successful_probes = 0
                    logger.info("circuit_breaker.closed_restored", breaker=self.name)
            elif self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0

    async def record_failure(self, error: Exception) -> None:
        """Record downstream failure and trip breaker if threshold exceeded."""
        async with self._lock:
            self._consecutive_failures += 1
            now = time.monotonic()
            logger.warning(
                "circuit_breaker.failure_recorded",
                breaker=self.name,
                consecutive_failures=self._consecutive_failures,
                threshold=self.failure_threshold,
                error=str(error),
            )

            if self._state in {CircuitState.CLOSED, CircuitState.HALF_OPEN}:
                if (
                    self._consecutive_failures >= self.failure_threshold
                    or self._state == CircuitState.HALF_OPEN
                ):
                    self._state = CircuitState.OPEN
                    self._tripped_at = now
                    logger.info(
                        "circuit_breaker.tripped_open",
                        breaker=self.name,
                        recovery_timeout_seconds=self.recovery_timeout_seconds,
                    )

    async def __aenter__(self) -> "CircuitBreaker":
        async with self._lock:
            current_state = self.state
            if current_state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is OPEN. Requests blocked until timeout."
                )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_val is not None:
            if not isinstance(exc_val, CircuitOpenError):
                await self.record_failure(exc_val)
            # Re-raise error to caller
            return False

        await self.record_success()
        return False
