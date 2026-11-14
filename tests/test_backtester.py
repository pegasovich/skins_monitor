"""Unit tests for Backtesting Engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from collectibles.analyzer.backtester import BacktestEngine
from collectibles.core.models import DataStatus, PricePoint


def make_tick(source: str, price: Decimal, time_offset_sec: int) -> PricePoint:
    base_time = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
    return PricePoint(
        source_id=source,
        external_item_id=f"tick_{source}_{time_offset_sec}",
        item_identity_hash="backtest_skin_hash",
        raw_price=price,
        raw_currency="USD",
        normalized_price=price,
        base_currency="USD",
        event_time=base_time + timedelta(seconds=time_offset_sec),
        status=DataStatus.FRESH,
        confidence=Decimal("0.95"),
        correlation_id=f"corr_{time_offset_sec}",
    )


def test_backtest_engine_simulation_and_metrics() -> None:
    engine = BacktestEngine()

    # Sequence of ticks:
    # t=0: CSFloat listing at $100
    # t=10: Skinport listing at $130 (profitable arbitrage)
    # t=20: Skinport drops to $102 (no arbitrage)
    events = [
        make_tick("csfloat", Decimal("100.00"), 0),
        make_tick("skinport", Decimal("130.00"), 10),
        make_tick("skinport", Decimal("102.00"), 20),
    ]

    report = engine.run(events, slippage_percent=Decimal("0.01"))

    assert report.total_events_processed == 3
    assert report.total_signals_generated == 1
    assert report.profitable_signals == 1
    assert report.precision == Decimal("1.0000")
    assert report.false_discovery_rate == Decimal("0.0000")
    assert report.total_net_profit_usd > Decimal("0.0")
    assert report.max_drawdown_usd >= Decimal("0.0")
