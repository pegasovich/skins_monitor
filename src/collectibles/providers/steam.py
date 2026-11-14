"""Production live adapter for Steam Community Market API."""

import re
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from collectibles.core.http_client import ResilientHttpClient
from collectibles.core.identity import CS2ItemIdentity
from collectibles.core.models import DataStatus, PricePoint
from collectibles.core.rate_limiter import InMemoryTokenBucket
from collectibles.providers.base import BaseProvider

logger = structlog.get_logger(__name__)


class SteamPriceOverviewPayload(BaseModel):
    """Schema model for Steam Market priceoverview endpoint."""

    model_config = ConfigDict(extra="ignore")

    success: bool
    lowest_price: str | None = None
    median_price: str | None = None
    volume: str | None = None


class SteamMarketAdapter(BaseProvider):
    """Adapter for official Steam Community Market pricing with strict rate limits."""

    BASE_URL = "https://steamcommunity.com"

    def __init__(
        self,
        api_key: str | None = None,
        provider_id: str = "steam",
        rate_per_sec: float = 0.33,  # Strict conservative rate: ~1 req every 3 seconds
    ) -> None:
        super().__init__(provider_id=provider_id)
        self.api_key = api_key
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://steamcommunity.com/market/",
        }
        self.http_client = ResilientHttpClient(
            base_url=self.BASE_URL,
            headers=headers,
            rate_limiter=InMemoryTokenBucket(rate_per_second=rate_per_sec, capacity=2.0),
            rate_limit_key="steam_market_api",
        )
        self._price_cache: dict[str, tuple[PricePoint, float]] = {}
        self.cache_ttl: float = 300.0  # 5 minutes cache TTL
        self._cooldown_until: float = 0.0
        self.circuit_breaker.recovery_timeout_seconds = 180.0

    @staticmethod
    def _parse_currency_string(price_str: str | None) -> Decimal | None:
        """Parse strings like '$12.45' or '12,45€' into clean Decimal USD."""
        if not price_str:
            return None
        # Extract digits and dot/comma
        cleaned = re.sub(r"[^\d.,]", "", price_str).strip()
        if not cleaned:
            return None
        # Handle comma as decimal separator if no period
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")  # thousand separator

        try:
            return Decimal(cleaned).quantize(Decimal("0.01"))
        except Exception:
            return None

    @staticmethod
    def _parse_volume_string(volume_str: str | None) -> int:
        """Parse volume strings like '1,420' into integer."""
        if not volume_str:
            return 0
        cleaned = re.sub(r"[^\d]", "", volume_str)
        try:
            return int(cleaned)
        except ValueError:
            return 0

    async def health_check(self) -> bool:
        if not self.is_available:
            return False
        try:
            resp = await self.http_client.get(
                "/market/priceoverview/",
                params={
                    "appid": 730,
                    "currency": 1,
                    "market_hash_name": "AK-47 | Redline (Field-Tested)",
                },
                max_attempts=1,
            )
            return resp.status_code == 200 and resp.json().get("success", False)
        except Exception:
            return False

    def parse_overview_to_price_point(
        self, market_hash_name: str, raw_data: dict[str, Any]
    ) -> PricePoint | None:
        """Validate raw Steam JSON into canonical PricePoint."""
        model = SteamPriceOverviewPayload.model_validate(raw_data)
        if not model.success:
            return None
        self.record_validation_success()

        # Prefer lowest_price, fallback to median_price
        price_dec = self._parse_currency_string(model.lowest_price) or self._parse_currency_string(
            model.median_price
        )
        if price_dec is None or price_dec <= Decimal("0.0"):
            return None

        identity = CS2ItemIdentity(market_hash_name=market_hash_name)
        identity_hash = identity.compute_identity_hash(strict_mode=False)

        return PricePoint(
            source_id=self.provider_id,
            external_item_id=f"steam_{identity_hash[:16]}",
            item_identity_hash=identity_hash,
            market_hash_name=market_hash_name,
            raw_price=price_dec,
            raw_currency="USD",
            normalized_price=price_dec,
            base_currency="USD",
            event_time=datetime.now(UTC),
            status=DataStatus.FRESH,
            confidence=Decimal("0.99"),  # Steam is benchmark reference
            correlation_id=f"steam_{identity_hash[:12]}",
        )

    async def fetch_item_price(self, market_hash_name: str) -> PricePoint | None:
        """Fetch real-time market overview for a specific CS2 item."""
        if not self.is_available:
            logger.warning("steam.fetch_skipped_provider_unavailable")
            return None

        now = time.time()
        if now < self._cooldown_until:
            if market_hash_name in self._price_cache:
                return self._price_cache[market_hash_name][0]
            return None

        if market_hash_name in self._price_cache:
            cached_pt, ts = self._price_cache[market_hash_name]
            if now - ts < self.cache_ttl:
                return cached_pt

        try:
            async with self.circuit_breaker:
                resp = await self.http_client.get(
                    "/market/priceoverview/",
                    params={"appid": 730, "currency": 1, "market_hash_name": market_hash_name},
                    max_attempts=1,
                )
                if resp.status_code != 200:
                    return None

                raw_json = resp.json()
                point = self.parse_overview_to_price_point(market_hash_name, raw_json)
                if point is not None:
                    self._price_cache[market_hash_name] = (point, now)
                return point
        except Exception as e:
            self._cooldown_until = time.time() + 180.0  # 3 minutes polite cooldown
            logger.info(
                "steam.cooldown_activated",
                cooldown_seconds=180,
                item=market_hash_name,
                error=str(e)[:60],
            )
            if market_hash_name in self._price_cache:
                return self._price_cache[market_hash_name][0]
            return None

        return None

    async def fetch_listings(
        self, limit: int = 50, target_items: list[str] | None = None
    ) -> list[PricePoint]:
        """Fetch prices for target skins or fallback to benchmark liquidity items."""
        now = time.time()
        if now < self._cooldown_until:
            return [
                self._price_cache[name][0]
                for name in (target_items or [])[:limit]
                if name in self._price_cache
            ]
        BENCHMARK_SKINS = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Field-Tested)",
            "M4A4 | Asiimov (Field-Tested)",
            "Desert Eagle | Printstream (Field-Tested)",
            "USP-S | Kill Confirmed (Field-Tested)",
            "AK-47 | Vulcan (Field-Tested)",
            "Glock-18 | Water Elemental (Field-Tested)",
            "Recoil Case",
            "Dreams & Nightmares Case",
            "Revolution Case",
        ]

        query_list = target_items if (target_items and len(target_items) > 0) else BENCHMARK_SKINS

        results: list[PricePoint] = []
        for name in query_list[:limit]:
            try:
                point = await self.fetch_item_price(name)
                if point is not None:
                    results.append(point)
            except Exception as e:
                logger.debug("steam.item_fetch_failed", item=name, error=str(e))

        logger.info("steam.fetch_success", count=len(results), targets=len(query_list[:limit]))
        return results
