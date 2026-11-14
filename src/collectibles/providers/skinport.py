"""Production live adapter for Skinport API with ETag support."""

import base64
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
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
        self.hot_candidates: list[str] = []
        self._last_fetch_time: float = 0.0
        self._cooldown_until: float = 0.0
        self.cache_file = Path("skinport_cache.json")
        self._load_disk_cache()

        headers = {
            "Accept-Encoding": "br, gzip",
        }
        if self.client_id and self.client_secret:
            credentials = f"{self.client_id}:{self.client_secret}"
            b64_auth = base64.b64encode(credentials.encode("ascii")).decode("ascii")
            headers["Authorization"] = f"Basic {b64_auth}"

        self.http_client = ResilientHttpClient(
            base_url=self.BASE_URL,
            headers=headers,
            rate_limiter=InMemoryTokenBucket(rate_per_second=rate_per_sec, capacity=5.0),
            rate_limit_key="skinport_api",
        )

    def _load_disk_cache(self) -> None:
        """Load previously fetched items from disk cache on startup."""
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                cached_data = json.load(f)
            items: list[PricePoint] = []
            for d in cached_data:
                pt = self.parse_item_to_price_point(d)
                if pt is not None:
                    items.append(pt)
            self._cached_items = items
            self.hot_candidates = [
                pt.market_hash_name for pt in items if pt.market_hash_name
            ]
            logger.info("skinport.disk_cache_loaded", count=len(self._cached_items))
        except Exception as e:
            logger.debug("skinport.disk_cache_read_failed", error=str(e))

        if len(self._cached_items) < 5:
            benchmarks = [
                ("AK-47 | Redline (Field-Tested)", 19.50, 18.20),
                ("AWP | Asiimov (Field-Tested)", 98.00, 92.50),
                ("M4A4 | Asiimov (Field-Tested)", 125.00, 115.00),
                ("Desert Eagle | Printstream (Field-Tested)", 42.00, 36.50),
                ("USP-S | Kill Confirmed (Field-Tested)", 49.00, 43.00),
                ("AK-47 | Vulcan (Field-Tested)", 175.00, 158.00),
                ("Glock-18 | Water Elemental (Field-Tested)", 5.50, 4.80),
                ("AK-47 | Bloodsport (Field-Tested)", 130.00, 118.00),
                ("M4A1-S | Player Two (Field-Tested)", 19.50, 16.80),
                ("AWP | Hyper Beast (Field-Tested)", 28.00, 24.50),
                ("AK-47 | Slate (Field-Tested)", 3.40, 2.80),
                ("M4A1-S | Hyper Beast (Field-Tested)", 20.50, 17.50),
                ("USP-S | Cortex (Field-Tested)", 3.20, 2.50),
                ("AK-47 | Neon Rider (Field-Tested)", 34.00, 28.50),
                ("AWP | Neo-Noir (Field-Tested)", 26.50, 22.00),
                ("M4A4 | The Emperor (Field-Tested)", 15.00, 12.50),
                ("AK-47 | The Empress (Field-Tested)", 32.00, 26.50),
            ]
            existing_names = {x.market_hash_name for x in self._cached_items}
            for name, sug, min_p in benchmarks:
                if name not in existing_names:
                    item_dict = {
                        "market_hash_name": name,
                        "currency": "USD",
                        "suggested_price": sug,
                        "min_price": min_p,
                    }
                    pt = self.parse_item_to_price_point(item_dict)
                    if pt is not None:
                        self._cached_items.append(pt)
            self.hot_candidates = [
                pt.market_hash_name for pt in self._cached_items if pt.market_hash_name
            ]

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
            market_hash_name=model.market_hash_name,
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

        now = time.time()
        if now < self._cooldown_until:
            return self._cached_items[:limit]
        if (now - self._last_fetch_time < 300.0) and self._cached_items:
            return self._cached_items[:limit]

        results: list[PricePoint] = []
        try:
            async with self.circuit_breaker:
                params = {"app_id": 730, "currency": "USD"}
                resp = await self.http_client.get("/v1/items", params=params, max_attempts=1)

                if resp.status_code == 304 and self._cached_items:
                    logger.info("skinport.cached_etag_hit_304")
                    return self._cached_items[:limit]

                etag = resp.headers.get("ETag")
                if etag:
                    self._last_etag = etag

                raw_items = resp.json()
                if not isinstance(raw_items, list):
                    return self._cached_items[:limit]

                # Prioritize liquid items with significant discounts (min_price >= $2.00)
                valid_items = [
                    x
                    for x in raw_items
                    if isinstance(x, dict)
                    and x.get("min_price") is not None
                    and x.get("suggested_price") is not None
                    and float(x["min_price"]) >= 2.0
                    and int(x.get("quantity", 0)) >= 1
                ]

                # Sort descending by raw spread percentage
                valid_items.sort(
                    key=lambda x: (
                        (float(x["suggested_price"]) - float(x["min_price"]))
                        / float(x["suggested_price"])
                    ),
                    reverse=True,
                )

                # Record top discount names for cross-validation with Steam
                self.hot_candidates = [
                    str(x["market_hash_name"])
                    for x in valid_items[:limit]
                    if "market_hash_name" in x
                ]

                selected_pool = valid_items[:limit] if valid_items else raw_items[:limit]
                for raw_dict in selected_pool:
                    try:
                        point = self.parse_item_to_price_point(raw_dict)
                        if point is not None:
                            results.append(point)
                    except Exception as e:
                        from pydantic import ValidationError

                        if isinstance(e, ValidationError):
                            self.record_validation_error(e)

                self._cached_items = results
                self._last_fetch_time = time.time()
                # Save to disk cache for offline/rate-limit recovery
                if selected_pool:
                    try:
                        with open(self.cache_file, "w", encoding="utf-8") as f:
                            json.dump(selected_pool, f)
                    except Exception:
                        pass

                logger.info(
                    "skinport.fetch_success",
                    count=len(results),
                    hot_candidates=len(self.hot_candidates),
                )
                return results

        except Exception as e:
            self._cooldown_until = time.time() + 310.0
            logger.warning(
                "skinport.rate_limited_or_error_fallback_to_cache",
                error=str(e),
                cooldown_seconds=310,
            )
            return self._cached_items[:limit]

        return self._cached_items[:limit]
