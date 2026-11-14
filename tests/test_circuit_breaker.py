"""Unit tests for CircuitBreaker state transitions."""

import asyncio

import pytest

from collectibles.core.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


@pytest.mark.asyncio
async def test_circuit_breaker_transitions_to_open_on_failures() -> None:
    breaker = CircuitBreaker(name="test_service", failure_threshold=3, recovery_timeout_seconds=0.2)
    assert breaker.state == CircuitState.CLOSED

    # Trigger 2 failures (below threshold)
    for _ in range(2):
        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("Transient downstream error")
    assert breaker.state == CircuitState.CLOSED

    # 3rd failure trips breaker
    with pytest.raises(ValueError):
        async with breaker:
            raise ValueError("Tripping error")
    assert breaker.state == CircuitState.OPEN

    # In OPEN state, calls are immediately rejected without executing block
    with pytest.raises(CircuitOpenError):
        async with breaker:
            pytest.fail("Should not execute inner block when OPEN")


@pytest.mark.asyncio
async def test_circuit_breaker_recovers_via_half_open() -> None:
    breaker = CircuitBreaker(
        name="recovering_service",
        failure_threshold=1,
        recovery_timeout_seconds=0.1,
        half_open_success_threshold=2,
    )

    # Trip breaker to OPEN
    with pytest.raises(RuntimeError):
        async with breaker:
            raise RuntimeError("Outage")
    assert breaker.state == CircuitState.OPEN

    # Wait for recovery timeout
    await asyncio.sleep(0.12)
    assert breaker.state == CircuitState.HALF_OPEN

    # First successful trial probe
    async with breaker:
        pass
    assert breaker.state == CircuitState.HALF_OPEN

    # Second successful probe restores CLOSED
    async with breaker:
        pass
    assert breaker.state == CircuitState.CLOSED
