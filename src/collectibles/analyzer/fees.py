"""Marketplace fee structures and net spread calculation engine."""

from decimal import ROUND_HALF_UP, Decimal

from collectibles.core.models import PlatformFeeConfig

# Default platform fee matrix
DEFAULT_PLATFORM_FEES: dict[str, PlatformFeeConfig] = {
    "steam": PlatformFeeConfig(
        platform_id="steam",
        seller_fee_percent=Decimal("0.1304"),  # Steam effective cut ~13-15%
        buyer_fee_percent=Decimal("0.0"),
        flat_fee=Decimal("0.0"),
        has_trade_lock=True,
    ),
    "csfloat": PlatformFeeConfig(
        platform_id="csfloat",
        seller_fee_percent=Decimal("0.02"),  # 2.0% seller fee
        buyer_fee_percent=Decimal("0.0"),
        flat_fee=Decimal("0.0"),
        has_trade_lock=True,
    ),
    "skinport": PlatformFeeConfig(
        platform_id="skinport",
        seller_fee_percent=Decimal("0.06"),  # 6.0% to 12.0%
        buyer_fee_percent=Decimal("0.0"),
        flat_fee=Decimal("0.0"),
        has_trade_lock=False,  # bot inventory / instant
    ),
}


class FeeCalculator:
    """Calculates gross-to-net proceeds across different market configurations."""

    def __init__(self, custom_fees: dict[str, PlatformFeeConfig] | None = None) -> None:
        self.fee_matrix = custom_fees or DEFAULT_PLATFORM_FEES

    def get_config(self, platform_id: str) -> PlatformFeeConfig:
        """Fetch fee configuration or default to conservative 10% fee if unknown."""
        return self.fee_matrix.get(
            platform_id,
            PlatformFeeConfig(
                platform_id=platform_id,
                seller_fee_percent=Decimal("0.10"),
                buyer_fee_percent=Decimal("0.0"),
                flat_fee=Decimal("0.0"),
                has_trade_lock=True,
            ),
        )

    def calculate_buyer_cost(self, platform_id: str, listing_price: Decimal) -> Decimal:
        """Calculate total amount buyer pays including buyer-side fees."""
        cfg = self.get_config(platform_id)
        cost = listing_price * (Decimal("1.0") + cfg.buyer_fee_percent) + cfg.flat_fee
        return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_seller_proceeds(self, platform_id: str, listing_price: Decimal) -> Decimal:
        """Calculate net cash received by seller after platform deductions."""
        cfg = self.get_config(platform_id)
        proceeds = listing_price * (Decimal("1.0") - cfg.seller_fee_percent) - cfg.flat_fee
        if proceeds < Decimal("0.0"):
            return Decimal("0.0")
        return proceeds.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def compute_net_spread(
        self,
        buy_platform: str,
        buy_listing_price: Decimal,
        sell_platform: str,
        sell_listing_price: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Compute gross spread %, net spread %, and nominal net profit in USD.

        Returns:
            (gross_spread_percent, net_spread_percent, net_profit_nominal)
        """
        if buy_listing_price <= Decimal("0.0"):
            return Decimal("0.0"), Decimal("0.0"), Decimal("0.0")

        buy_total_cost = self.calculate_buyer_cost(buy_platform, buy_listing_price)
        sell_net_proceeds = self.calculate_seller_proceeds(sell_platform, sell_listing_price)

        gross_profit = sell_listing_price - buy_listing_price
        gross_spread_percent = (gross_profit / buy_listing_price) * Decimal("100")

        net_profit = sell_net_proceeds - buy_total_cost
        net_spread_percent = (net_profit / buy_total_cost) * Decimal("100")

        return (
            gross_spread_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            net_spread_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            net_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )
