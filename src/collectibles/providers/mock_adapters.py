"""Concrete data provider adapters for CSFloat and Skinport."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from collectibles.core.identity import CS2ItemIdentity
from collectibles.core.models import DataStatus, PricePoint
from collectibles.providers.base import BaseProvider


class CSFloatListingPayload(BaseModel):
    """Schema model for CSFloat API listing payload."""

    model_config = ConfigDict(extra="ignore")

    id: str
    price: int = Field(..., description="Price in cents (e.g. 15000 = $150.00)")
    market_hash_name: str
    float_value: float | None = None
    paint_seed: int | None = None
    paint_index: int | None = None
    is_stattrak: bool = False
    is_souvenir: bool = False


class CSFloatAdapter(BaseProvider):
    """Adapter for CSFloat marketplace listings."""

    def __init__(self, provider_id: str = "csfloat") -> None:
        super().__init__(provider_id=provider_id)

    async def health_check(self) -> bool:
        return not self.is_quarantined

    def parse_listing(self, raw_data: dict[str, Any]) -> PricePoint:
        """Parse raw JSON dict into validated PricePoint or raise ValidationError."""
        item = CSFloatListingPayload.model_validate(raw_data)
        self.record_validation_success()

        # Convert cents to Decimal USD
        decimal_price = (Decimal(str(item.price)) / Decimal("100")).quantize(Decimal("0.01"))
        float_dec = Decimal(str(item.float_value)) if item.float_value is not None else None

        identity = CS2ItemIdentity(
            market_hash_name=item.market_hash_name,
            paint_index=item.paint_index,
            paint_seed=item.paint_seed,
            float_value=float_dec,
            is_stattrak=item.is_stattrak,
            is_souvenir=item.is_souvenir,
        )

        identity_hash = identity.compute_identity_hash(strict_mode=False)

        return PricePoint(
            source_id=self.provider_id,
            external_item_id=item.id,
            item_identity_hash=identity_hash,
            raw_price=decimal_price,
            raw_currency="USD",
            normalized_price=decimal_price,
            base_currency="USD",
            event_time=datetime.now(UTC),
            status=DataStatus.FRESH,
            confidence=Decimal("0.95"),
            correlation_id=str(uuid.uuid4()),
        )

    async def fetch_listings(self, limit: int = 100) -> list[PricePoint]:
        # In Phase 1 unit testing, this is exercised with mock payloads or injected httpx client
        return []
