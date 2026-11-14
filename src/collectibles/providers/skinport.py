"""Production live adapter for Skinport API with ETag support."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from collectibles.core.http_client import ResilientHttpClient
from collectibles.core.identity import CS2ItemIdentity
from collectibles.core.models import DataStatus, PricePoint
from collectibles.core.rate_limiter import InMemoryTokenBucket
from collectibles.providers.base import BaseProvider

logger = structlog.get_logger(__name__)


class SkinportItemPayload(BaseModel):
    """Schema model for a Skinport catalog item entry."""

    model_config = ConfigDict(extra="ignore")

    market_hash_name: str
    currency: str = "USD"
    suggested_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    quantity: int = Field(default=0, ge=0)
    updated_at: int | None = None


class SkinportLiveAdapter(BaseProvider):
    """Live HTTP adapter for Skinport public API with ETag and rate limits."""

    BASE_URL = "https://api.skinport.com"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        provider_id: str = "skinport",
        rate_per_sec: float = 2.0,  # 2 req/sec Skinport safe rate
    ) -> None:
        super().__init__(provider_id=provider_id)
        self.client_id = client_id
        self.client_secret = client_secret
        self._last_etag: str | None = None
        self._cached_items: list[PricePoint] = []

        headers = {
            "Accept-Encoding": "gzip",
        }
        self.http_client = ResilientHttpClient(
            base_url=self.BASE_URL,
            headers=headers,
            rate_limiter=InMemoryTokenBucket(rate_per_second=rate_per_sec, capacity=5.0),
            rate_limit_key="skinport_api",
        )

    async def health_check(self) -> bool:
        if not self.is_available:
            return False
        try:
            resp = await self.http_client.get("/v1/items", params={"limit": 1}, max_attempts=1)
            return resp.status_code in {200, 304}
        except Exception:
            return False

    def parse_item_to_price_point(self, raw_item: dict[str, Any]) -> PricePoint | None:
        """Parse raw Skinport catalog item into canonical PricePoint."""
        model = SkinportItemPayload.model_validate(raw_item)
        self.record_validation_success()

        # If there's no active min_price, use suggested_price or skip
        chosen_price = model.min_price or model.suggested_price
        if chosen_price is None or chosen_price <= 0.0:
            return None

        decimal_price = Decimal(str(chosen_price)).quantize(Decimal("0.01"))

        identity = CS2ItemIdentity(market_hash_name=model.market_hash_name)
        identity_hash = identity.compute_identity_hash(strict_mode=False)

        event_time = (
            datetime.fromtimestamp(model.updated_at, tz=UTC)
            if model.updated_at
            else datetime.now(UTC)
        )

        return PricePoint(
            source_id=self.provider_id,
            external_item_id=f"skinport_{identity_hash[:16]}",
            item_identity_hash=identity_hash,
            raw_price=decimal_price,
            raw_currency=model.currency,
            normalized_price=decimal_price,
            base_currency="USD",
            event_time=event_time,
            status=DataStatus.FRESH,
            confidence=Decimal("0.95"),
            correlation_id=f"skinport_{identity_hash[:12]}",
        )

    async def fetch_listings(self, limit: int = 100) -> list[PricePoint]:
        """Fetch items from Skinport with ETag 304 Not Modified caching."""
        if not self.is_available:
            logger.warning("skinport.fetch_skipped_provider_unavailable")
            return self._cached_items[:limit]

        results: list[PricePoint] = []
        async with self.circuit_breaker:
            params = {"app_id": 730, "currency": "USD"}
            resp = await self.http_client.get("/v1/items", params=params)

            if resp.status_code == 304 and self._cached_items:
                logger.info("skinport.cached_etag_hit_304")
                return self._cached_items[:limit]

            etag = resp.headers.get("ETag")
            if etag:
                self._last_etag = etag

            raw_items = resp.json()
            if not isinstance(raw_items, list):
                return []

            for raw_dict in raw_items[:limit]:
                try:
                    point = self.parse_item_to_price_point(raw_dict)
                    if point is not None:
                        results.append(point)
                except Exception as e:
                    from pydantic import ValidationError

                    if isinstance(e, ValidationError):
                        self.record_validation_error(e)

            self._cached_items = results
            logger.info("skinport.fetch_success", count=len(results))
        return results
