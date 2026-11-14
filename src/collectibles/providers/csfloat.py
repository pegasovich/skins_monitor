"""Production live adapter for CSFloat marketplace API."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from collectibles.core.http_client import ResilientHttpClient
from collectibles.core.identity import CS2ItemIdentity, StickerInfo
from collectibles.core.models import DataStatus, PricePoint
from collectibles.core.rate_limiter import InMemoryTokenBucket
from collectibles.providers.base import BaseProvider

logger = structlog.get_logger(__name__)


class CSFloatStickerPayload(BaseModel):
    """Sticker info from CSFloat item schema."""

    model_config = ConfigDict(extra="ignore")

    slot: int = Field(default=0, ge=0, le=4)
    name: str = ""
    wear: float | None = None


class CSFloatItemPayload(BaseModel):
    """CSFloat item parameters."""

    model_config = ConfigDict(extra="ignore")

    market_hash_name: str
    float_value: float | None = None
    paint_seed: int | None = None
    paint_index: int | None = None
    is_stattrak: bool = False
    is_souvenir: bool = False
    stickers: list[CSFloatStickerPayload] = Field(default_factory=list)


class CSFloatListing(BaseModel):
    """Top-level CSFloat listing response object."""

    model_config = ConfigDict(extra="ignore")

    id: str
    price: int = Field(..., description="Price in USD cents")
    item: CSFloatItemPayload
    created_at: str | None = None


class CSFloatLiveAdapter(BaseProvider):
    """Live HTTP adapter for CSFloat B2B / public listings."""

    BASE_URL = "https://csfloat.com"

    def __init__(
        self,
        api_key: str | None = None,
        provider_id: str = "csfloat",
        rate_per_sec: float = 1.0,  # 1 req/sec strict rate limit
    ) -> None:
        super().__init__(provider_id=provider_id)
        self.api_key = api_key
        headers = {}
        if api_key:
            headers["Authorization"] = api_key

        self.http_client = ResilientHttpClient(
            base_url=self.BASE_URL,
            headers=headers,
            rate_limiter=InMemoryTokenBucket(rate_per_second=rate_per_sec, capacity=3.0),
            rate_limit_key="csfloat_api",
        )

    async def health_check(self) -> bool:
        """Verify liveness of CSFloat endpoint."""
        if not self.is_available:
            return False
        try:
            resp = await self.http_client.get(
                "/api/v1/listings", params={"limit": 1}, max_attempts=1
            )
            return resp.status_code == 200
        except Exception:
            return False

    def parse_listing_to_price_point(self, raw_listing: dict[str, Any]) -> PricePoint:
        """Validate raw json dictionary into canonical PricePoint."""
        model = CSFloatListing.model_validate(raw_listing)
        self.record_validation_success()

        # Convert cents to Decimal USD
        decimal_price = (Decimal(str(model.price)) / Decimal("100")).quantize(Decimal("0.01"))
        float_dec = (
            Decimal(str(model.item.float_value)) if model.item.float_value is not None else None
        )

        normalized_stickers = [
            StickerInfo(
                slot=s.slot,
                name=s.name,
                wear=Decimal(str(s.wear)) if s.wear is not None else None,
            )
            for s in model.item.stickers
            if s.name
        ]

        identity = CS2ItemIdentity(
            market_hash_name=model.item.market_hash_name,
            paint_index=model.item.paint_index,
            paint_seed=model.item.paint_seed,
            float_value=float_dec,
            is_stattrak=model.item.is_stattrak,
            is_souvenir=model.item.is_souvenir,
            stickers=normalized_stickers,
        )

        identity_hash = identity.compute_identity_hash(strict_mode=False)

        event_time = datetime.now(UTC)
        if model.created_at:
            try:
                event_time = datetime.fromisoformat(model.created_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        return PricePoint(
            source_id=self.provider_id,
            external_item_id=model.id,
            item_identity_hash=identity_hash,
            market_hash_name=model.item.market_hash_name,
            raw_price=decimal_price,
            raw_currency="USD",
            normalized_price=decimal_price,
            base_currency="USD",
            event_time=event_time,
            status=DataStatus.FRESH,
            confidence=Decimal("0.98"),
            correlation_id=f"csfloat_{model.id}",
        )

    async def fetch_listings(self, limit: int = 50) -> list[PricePoint]:
        """Fetch active listings from CSFloat API with quarantine & circuit breaker protection."""
        if not self.is_available:
            logger.warning("csfloat.fetch_skipped_provider_unavailable")
            return []

        if not self.api_key:
            logger.warning(
                "csfloat.api_key_not_configured",
                hint="CSFloat listings endpoint requires CSFLOAT_API_KEY in .env",
            )
            return []

        results: list[PricePoint] = []
        async with self.circuit_breaker:
            resp = await self.http_client.get(
                "/api/v1/listings",
                params={"limit": min(limit, 50), "sort_by": "most_recent"},
            )
            raw_data = resp.json()

            # CSFloat returns either a list of listings or a dict with 'data'
            listings_raw: list[dict[str, Any]] = (
                raw_data if isinstance(raw_data, list) else raw_data.get("data", [])
            )

            for item_dict in listings_raw:
                try:
                    price_point = self.parse_listing_to_price_point(item_dict)
                    results.append(price_point)
                except Exception as e:
                    from pydantic import ValidationError

                    if isinstance(e, ValidationError):
                        self.record_validation_error(e)
                    logger.debug("csfloat.parse_item_failed", error=str(e))

            logger.info("csfloat.fetch_success", count=len(results))
        return results
