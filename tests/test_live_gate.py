"""Unit tests for Live Mode Gate validation (§11)."""

import pytest

from collectibles.core.circuit_breaker import CircuitBreaker
from collectibles.core.config import Settings
from collectibles.core.live_gate import LiveGateValidator, LiveGateViolationError


def test_live_gate_blocks_without_operator_confirmation() -> None:
    validator = LiveGateValidator(settings=Settings())
    breaker = CircuitBreaker(name="csfloat")

    with pytest.raises(LiveGateViolationError, match="Explicit operator confirmation is missing"):
        validator.validate_transition_readiness(
            operator_id="admin_1",
            user_confirmed=False,
            git_commit_sha="0cb5a0e12345",
            circuit_breakers=[breaker],
            dlq_depth=0,
            kill_switch_verified=True,
        )


def test_live_gate_blocks_if_circuit_breaker_open() -> None:
    validator = LiveGateValidator(settings=Settings())
    breaker = CircuitBreaker(name="csfloat", failure_threshold=1)

    # Trip breaker
    try:
        raise ConnectionResetError("Outage")
    except ConnectionResetError as e:
        import asyncio

        asyncio.run(breaker.record_failure(e))

    with pytest.raises(LiveGateViolationError, match="Circuit breakers not in CLOSED state"):
        validator.validate_transition_readiness(
            operator_id="admin_1",
            user_confirmed=True,
            git_commit_sha="0cb5a0e12345",
            circuit_breakers=[breaker],
            dlq_depth=0,
            kill_switch_verified=True,
        )


def test_live_gate_blocks_if_dlq_not_empty() -> None:
    validator = LiveGateValidator(settings=Settings())
    breaker = CircuitBreaker(name="csfloat")

    with pytest.raises(LiveGateViolationError, match="Dead-Letter Queue has 3 unprocessed"):
        validator.validate_transition_readiness(
            operator_id="admin_1",
            user_confirmed=True,
            git_commit_sha="0cb5a0e12345",
            circuit_breakers=[breaker],
            dlq_depth=3,
            kill_switch_verified=True,
        )


def test_live_gate_approves_when_all_conditions_satisfied() -> None:
    validator = LiveGateValidator(settings=Settings())
    breaker = CircuitBreaker(name="csfloat")

    audit = validator.validate_transition_readiness(
        operator_id="lead_architect",
        user_confirmed=True,
        git_commit_sha="0cb5a0e12345",
        circuit_breakers=[breaker],
        dlq_depth=0,
        kill_switch_verified=True,
    )

    assert audit.operator_id == "lead_architect"
    assert audit.git_commit_sha == "0cb5a0e12345"
    assert audit.verified_kill_switch is True
