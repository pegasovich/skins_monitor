"""Live Mode Gate validator enforcing strict checklist before real-world operation."""

from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ConfigDict, Field

from collectibles.core.circuit_breaker import CircuitBreaker, CircuitState
from collectibles.core.config import Settings

logger = structlog.get_logger(__name__)


class LiveGateViolationError(Exception):
    """Raised when criteria for entering LIVE mode are violated."""


class LiveAuditEntry(BaseModel):
    """Immutable audit entry certifying transition to LIVE mode."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    git_commit_sha: str
    operator_id: str
    reason: str
    verified_kill_switch: bool


class LiveGateValidator:
    """Verifies that all pre-flight conditions are satisfied before disabling DRY_RUN."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate_transition_readiness(
        self,
        operator_id: str,
        user_confirmed: bool,
        git_commit_sha: str,
        circuit_breakers: list[CircuitBreaker],
        dlq_depth: int = 0,
        kill_switch_verified: bool = False,
    ) -> LiveAuditEntry:
        """Evaluate pre-flight checklist according to §11."""
        violations: list[str] = []

        # Gate 1: Explicit operator confirmation
        if not user_confirmed:
            violations.append("Explicit operator confirmation is missing.")

        # Gate 2: Commit SHA tracking
        if not git_commit_sha or len(git_commit_sha.strip()) < 7:
            violations.append("Valid Git commit SHA is required for audit traceability.")

        # Gate 3: All circuit breakers must be closed
        unhealthy_breakers = [b.name for b in circuit_breakers if b.state != CircuitState.CLOSED]
        if unhealthy_breakers:
            violations.append(f"Circuit breakers not in CLOSED state: {unhealthy_breakers}")

        # Gate 4: Dead-Letter Queue must be clean
        if dlq_depth > 0:
            violations.append(f"Dead-Letter Queue has {dlq_depth} unprocessed failed messages.")

        # Gate 5: Emergency kill-switch verified
        if not kill_switch_verified:
            violations.append(
                "STOP_ALL_OUTBOUND emergency kill-switch must be tested and verified."
            )

        if violations:
            logger.error("live_gate.transition_blocked", violations=violations)
            raise LiveGateViolationError(f"Live transition blocked: {'; '.join(violations)}")

        audit_entry = LiveAuditEntry(
            git_commit_sha=git_commit_sha,
            operator_id=operator_id,
            reason="Pre-flight checklist verified; all gates passed.",
            verified_kill_switch=kill_switch_verified,
        )

        logger.info(
            "live_gate.transition_authorized",
            operator=operator_id,
            commit=git_commit_sha,
        )

        return audit_entry
