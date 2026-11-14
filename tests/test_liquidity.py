"""Unit tests for Liquidity Engine and Wash-Trading detection."""

from datetime import UTC, datetime
from decimal import Decimal

from collectibles.analyzer.detector import OpportunityDetector
from collectibles.analyzer.liquidity import HistoricalSalesSummary, LiquidityEngine
from collectibles.core.models import DataStatus, LiquidityTier, PricePoint


def make_sample_price(source_id: str, price: Decimal) -> PricePoint:
    return PricePoint(
        source_id=source_id,
        external_item_id=f"ext_{source_id}",
        item_identity_hash="test_identity_hash_123",
        raw_price=price,
        raw_currency="USD",
        normalized_price=price,
        base_currency="USD",
        event_time=datetime.now(UTC),
        status=DataStatus.FRESH,
        confidence=Decimal("0.95"),
        correlation_id="corr-1",
    )


def test_liquidity_tier_classification() -> None:
    # 24+ sales / 24h -> ULTRA_HIGH
    assert LiquidityEngine.classify_liquidity(25, 100) == LiquidityTier.ULTRA_HIGH
    # 10+ sales / 24h -> HIGH
    assert LiquidityEngine.classify_liquidity(12, 50) == LiquidityTier.HIGH
    # 2 sales / 24h -> MEDIUM
    assert LiquidityEngine.classify_liquidity(3, 20) == LiquidityTier.MEDIUM
    # 1 sale / 24h -> LOW
    assert LiquidityEngine.classify_liquidity(1, 4) == LiquidityTier.LOW
    # 0 sales -> ILLIQUID
    assert LiquidityEngine.classify_liquidity(0, 1) == LiquidityTier.ILLIQUID


def test_wash_trading_detection_on_thin_volume() -> None:
    # Item normally trades at $50 (std dev = $5), but listing at $150 with only 1 sale in 24h
    summary = HistoricalSalesSummary(
        market_hash_name="USP-S | Kill Confirmed (Field-Tested)",
        sales_count_24h=1,
        sales_count_7d=10,
        median_price_7d=Decimal("50.00"),
        vwap_7d=Decimal("51.00"),
        price_std_dev=Decimal("5.00"),
    )

    is_wash, reason = LiquidityEngine.detect_wash_trading(
        observed_price=Decimal("150.00"),
        summary=summary,
    )
    assert is_wash is True
    assert "Extreme deviation" in reason or "above median" in reason


def test_detector_filters_wash_trading_and_illiquid() -> None:
    detector = OpportunityDetector(min_net_spread_percent=Decimal("5.0"))

    buy_point = make_sample_price("csfloat", Decimal("100.00"))
    sell_point = make_sample_price("skinport", Decimal("250.00"))

    # Summary showing fake pump / wash trading
    manipulated_summary = HistoricalSalesSummary(
        market_hash_name="Glock-18 | Fade",
        sales_count_24h=0,
        sales_count_7d=2,
        median_price_7d=Decimal("100.00"),
        vwap_7d=Decimal("100.00"),
        price_std_dev=Decimal("10.00"),
    )

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="Glock-18 | Fade",
        sales_summary=manipulated_summary,
    )

    assert signal is None  # Blocked by wash trading & illiquid filter
