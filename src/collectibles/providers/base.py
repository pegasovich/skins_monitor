"""Base provider interfaces, auto-quarantine, and provider registry."""

import abc
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from collectibles.core.models import PricePoint

logger = structlog.get_logger(__name__)


class ProviderQuarantinedError(Exception):
    """Raised when an adapter is temporarily quarantined due to schema drift or errors."""


class BaseProvider(abc.ABC):
    """Abstract base class for all collectible market data providers."""

    def __init__(self, provider_id: str, max_consecutive_validation_errors: int = 5) -> None:
        self.provider_id = provider_id
        self.max_consecutive_validation_errors = max_consecutive_validation_errors
        self._consecutive_errors: int = 0
        self._quarantined_until: datetime | None = None

    @property
    def is_quarantined(self) -> bool:
        """Check whether provider is currently locked in quarantine."""
        if self._quarantined_until is None:
            return False
        now = datetime.now(UTC)
        if now < self._quarantined_until:
            return True
        # Quarantine expired, reset
        self._quarantined_until = None
        self._consecutive_errors = 0
        logger.info("provider.quarantine_cleared", provider_id=self.provider_id)
        return False

    def record_validation_success(self) -> None:
        """Reset consecutive error counter on valid payload ingestion."""
        if self._consecutive_errors > 0:
            self._consecutive_errors = 0

    def record_validation_error(self, err: ValidationError, duration_seconds: int = 900) -> None:
        """Increment error count and trigger auto-quarantine if threshold reached (§8)."""
        self._consecutive_errors += 1
        logger.warning(
            "provider.validation_error",
            provider_id=self.provider_id,
            consecutive_errors=self._consecutive_errors,
            threshold=self.max_consecutive_validation_errors,
            error=str(err),
        )

        if self._consecutive_errors >= self.max_consecutive_validation_errors:
            now = datetime.now(UTC)
            self._quarantined_until = datetime.fromtimestamp(
                now.timestamp() + duration_seconds, tz=UTC
            )
            logger.critical(
                "provider.auto_quarantine_triggered",
                provider_id=self.provider_id,
                quarantined_until=self._quarantined_until.isoformat(),
                reason="Consecutive schema validation errors",
            )

    @abc.abstractmethod
    async def fetch_listings(self, limit: int = 100) -> list[PricePoint]:
        """Fetch and normalize latest listings from the provider."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Perform provider liveness and readiness probe."""


class ProviderRegistry:
    """Registry maintaining active data provider adapters."""

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}

    def register(self, provider: BaseProvider) -> None:
        """Register a provider instance."""
        self._providers[provider.provider_id] = provider
        logger.info("provider_registry.registered", provider_id=provider.provider_id)

    def get(self, provider_id: str) -> BaseProvider | None:
        """Retrieve registered provider by ID."""
        return self._providers.get(provider_id)

    def list_active(self) -> list[BaseProvider]:
        """Return all non-quarantined providers."""
        return [p for p in self._providers.values() if not p.is_quarantined]
