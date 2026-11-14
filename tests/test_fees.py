"""Unit tests for fee calculations and exact Decimal mathematics."""

from decimal import Decimal

from collectibles.analyzer.fees import FeeCalculator


def test_decimal_precision_no_float_rounding() -> None:
    calc = FeeCalculator()
    # Buying at $100 on CSFloat (0% buyer fee), selling at $110 on Skinport (6% seller fee)
    # Buy cost: $100.00
    # Sell proceeds: 110 * 0.94 = $103.40
    # Net profit: $3.40
    # Net spread: 3.40%
    gross, net, profit = calc.compute_net_spread(
        buy_platform="csfloat",
        buy_listing_price=Decimal("100.00"),
        sell_platform="skinport",
        sell_listing_price=Decimal("110.00"),
    )

    assert gross == Decimal("10.00")
    assert net == Decimal("3.40")
    assert profit == Decimal("3.40")


def test_gross_profit_turned_loss_after_steam_fee() -> None:
    calc = FeeCalculator()
    # Buy at $100 on CSFloat, sell at $110 on Steam (13.04% seller fee)
    # Steam proceeds: 110 * (1 - 0.1304) = 110 * 0.8696 = 95.656 -> $95.66
    # Net profit: 95.66 - 100 = -$4.34
    gross, net, profit = calc.compute_net_spread(
        buy_platform="csfloat",
        buy_listing_price=Decimal("100.00"),
        sell_platform="steam",
        sell_listing_price=Decimal("110.00"),
    )

    assert gross == Decimal("10.00")  # Grossly looks like +10%
    assert profit < Decimal("0.0")  # But actually guaranteed net loss
    assert net < Decimal("0.0")
