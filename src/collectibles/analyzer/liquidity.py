"""Market Liquidity Analysis and Wash-Trading / Manipulation Detector."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from collectibles.core.models import LiquidityTier


class HistoricalSalesSummary(BaseModel):
    """Aggregated market sales activity for an item."""

    model_config = ConfigDict(frozen=True)

    market_hash_name: str
    sales_count_24h: int = Field(default=0, ge=0)
    sales_count_7d: int = Field(default=0, ge=0)

    median_price_7d: Decimal = Field(..., description="Median transaction price over 7 days")
    vwap_7d: Decimal = Field(..., description="Volume Weighted Average Price over 7 days")
    price_std_dev: Decimal = Field(default=Decimal("0.0"), ge=Decimal("0.0"))


class LiquidityEngine:
    """Evaluates market depth, sales velocity, and flags manipulative wash trades."""

    @staticmethod
    def classify_liquidity(sales_count_24h: int, sales_count_7d: int) -> LiquidityTier:
        """Classify item liquidity into risk tiers (§19)."""
        if sales_count_24h >= 24:
            return LiquidityTier.ULTRA_HIGH
        if sales_count_24h >= 10:
            return LiquidityTier.HIGH
        if sales_count_24h >= 2 or sales_count_7d >= 15:
            return LiquidityTier.MEDIUM
        if sales_count_24h >= 1 or sales_count_7d >= 3:
            return LiquidityTier.LOW
        return LiquidityTier.ILLIQUID

    @staticmethod
    def detect_wash_trading(
        observed_price: Decimal,
        summary: HistoricalSalesSummary,
        z_threshold: float = 3.0,
    ) -> tuple[bool, str]:
        """Verify whether an observed price is a potential wash trade or pump-and-dump artifact.

        Returns:
            (is_suspicious, reason)
        """
        # 1. Zero liquidity items cannot be reliably priced
        if summary.sales_count_7d == 0:
            return True, "Zero historical sales in 7-day window"

        # 2. Extreme deviation from median on thin volume
        if summary.price_std_dev > Decimal("0.0"):
            diff = float(observed_price - summary.median_price_7d)
            std_dev = float(summary.price_std_dev)
            z_score = diff / std_dev

            if abs(z_score) > z_threshold and summary.sales_count_24h < 3:
                vol = summary.sales_count_24h
                return True, f"Extreme deviation (Z={z_score:.2f}) on low 24h vol ({vol})"

        # 3. Ratio sanity check: price > 2.5x median with <= 1 sale today
        if summary.median_price_7d > Decimal("0.0"):
            ratio = observed_price / summary.median_price_7d
            if ratio > Decimal("2.5") and summary.sales_count_24h <= 1:
                return True, f"Price {ratio:.2f}x above median with negligible 24h volume"

        return False, "Legitimate"
