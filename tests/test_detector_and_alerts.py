"""Tests for OpportunityDetector and AlertEngine."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collectibles.alerts.engine import AlertEngine
from collectibles.analyzer.detector import OpportunityDetector
from collectibles.core.config import Settings
from collectibles.core.models import DataStatus, LiquidityTier, PricePoint


def make_sample_price(
    source_id: str, price: Decimal, status: DataStatus = DataStatus.FRESH
) -> PricePoint:
    return PricePoint(
        source_id=source_id,
        external_item_id=f"ext_{source_id}",
        item_identity_hash="test_identity_hash_123",
        raw_price=price,
        raw_currency="USD",
        normalized_price=price,
        base_currency="USD",
        event_time=datetime.now(UTC),
        status=status,
        confidence=Decimal("0.95"),
        correlation_id="corr-1",
    )


def test_detector_finds_profitable_net_arbitrage() -> None:
    detector = OpportunityDetector(min_net_spread_percent=Decimal("3.0"))

    # Buy on CSFloat for $100 (2% seller fee for seller, 0% buyer fee for us = $100 cost)
    # Sell on Skinport for $120 (6% seller fee, net proceeds = $112.80)
    # Net profit = $12.80, Net spread = 12.8%
    buy_point = make_sample_price("csfloat", Decimal("100.00"))
    sell_point = make_sample_price("skinport", Decimal("120.00"))

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="AWP | Asiimov (Field-Tested)",
        liquidity_tier=LiquidityTier.HIGH,
    )

    assert signal is not None
    assert signal.net_spread_percent == Decimal("12.80")
    assert signal.net_profit_nominal == Decimal("12.80")
    assert signal.trade_lock_risk is True  # CSFloat has 7d trade lock


def test_detector_rejects_unprofitable_net_spread() -> None:
    detector = OpportunityDetector(min_net_spread_percent=Decimal("5.0"))

    # Buy at $100 on CSFloat, sell at $104 on Skinport
    # Net proceeds on Skinport: 104 * 0.94 = $97.76 (loss!)
    buy_point = make_sample_price("csfloat", Decimal("100.00"))
    sell_point = make_sample_price("skinport", Decimal("104.00"))

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="AWP | Asiimov (Field-Tested)",
    )

    assert signal is None


def test_detector_rejects_stale_data() -> None:
    detector = OpportunityDetector()
    buy_point = make_sample_price("csfloat", Decimal("100.00"), status=DataStatus.STALE)
    sell_point = make_sample_price("skinport", Decimal("150.00"))

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="AWP | Asiimov (Field-Tested)",
    )

    assert signal is None


@pytest.mark.asyncio
async def test_alert_engine_dry_run_and_kill_switch() -> None:
    detector = OpportunityDetector()
    buy_point = make_sample_price("csfloat", Decimal("100.00"))
    sell_point = make_sample_price("skinport", Decimal("130.00"))

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="AK-47 | Case Hardened",
    )
    assert signal is not None

    # Test 1: DRY_RUN=true dispatches safely without error
    settings = Settings(dry_run=True, stop_all_outbound=False)
    engine = AlertEngine(settings=settings)
    dispatched = await engine.dispatch(signal)
    assert dispatched is True

    # Test 2: De-duplication blocks immediate repeat
    is_dupe = await engine.dispatch(signal)
    assert is_dupe is False

    # Test 3: Emergency kill-switch STOP_ALL_OUTBOUND
    kill_settings = Settings(dry_run=False, stop_all_outbound=True)
    blocked_engine = AlertEngine(settings=kill_settings)
    assert await blocked_engine.dispatch(signal) is False


def test_detector_uses_reference_price_for_sell_side() -> None:
    detector = OpportunityDetector(min_net_spread_percent=Decimal("3.0"))

    buy_point = make_sample_price("skinport", Decimal("100.00"))
    # Sell point on CSFloat has asking price $150, but reference price is $110
    sell_point = PricePoint(
        source_id="csfloat",
        external_item_id="ext_csfloat",
        item_identity_hash="test_identity_hash_123",
        raw_price=Decimal("135.00"),  # EUR price
        raw_currency="EUR",
        normalized_price=Decimal("150.00"),  # USD ask
        reference_price=Decimal("110.00"),  # USD reference price
        base_currency="USD",
        event_time=datetime.now(UTC),
        status=DataStatus.FRESH,
        confidence=Decimal("0.95"),
        correlation_id="corr-1",
    )

    signal = detector.evaluate_arbitrage_pair(
        buy_point=buy_point,
        sell_point=sell_point,
        market_hash_name="AK-47 | Vulcan (Field-Tested)",
    )

    assert signal is not None
    # Sell proceeds must be based on $110 (CSFloat fee is 2% -> $110 * 0.98 = $107.80)
    # Net profit: 107.80 - 100.00 = 7.80
    assert signal.net_profit_nominal == Decimal("7.80")
    assert signal.net_spread_percent == Decimal("7.80")
    # Raw EUR sell price must be recomputed proportionally
    assert signal.sell_raw_price == Decimal("99.00")  # 110 * (135/150) = 99.00
