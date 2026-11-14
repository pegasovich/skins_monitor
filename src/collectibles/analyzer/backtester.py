"""Deterministic Backtesting Engine with slippage and fee awareness."""

from decimal import ROUND_HALF_UP, Decimal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from collectibles.analyzer.detector import OpportunityDetector
from collectibles.analyzer.fees import FeeCalculator
from collectibles.core.models import LiquidityTier, PricePoint

logger = structlog.get_logger(__name__)


class BacktestReport(BaseModel):
    """Statistical summary of historical strategy simulation."""

    model_config = ConfigDict(frozen=True)

    total_events_processed: int
    total_signals_generated: int
    profitable_signals: int
    unprofitable_signals: int

    precision: Decimal = Field(
        ..., description="Proportion of true positive profitable trades (0.0 - 1.0)"
    )
    false_discovery_rate: Decimal = Field(..., description="Proportion of false positive signals")

    total_net_profit_usd: Decimal
    max_drawdown_usd: Decimal
    slippage_percent_applied: Decimal


class BacktestEngine:
    """Simulates arbitrage detection on historical ticks without look-ahead bias."""

    def __init__(
        self,
        detector: OpportunityDetector | None = None,
        fee_calculator: FeeCalculator | None = None,
    ) -> None:
        self.detector = detector or OpportunityDetector()
        self.fee_calculator = fee_calculator or FeeCalculator()

    def run(
        self,
        price_events: list[PricePoint],
        slippage_percent: Decimal = Decimal("0.005"),  # 0.5% default slippage
    ) -> BacktestReport:
        """Execute replay simulation on a stream of historical price points."""
        # 1. Enforce strict chronological replay (No look-ahead bias)
        sorted_events = sorted(price_events, key=lambda p: p.event_time)

        # Track latest known price per (source, identity_hash)
        latest_prices: dict[tuple[str, str], PricePoint] = {}

        total_signals = 0
        profitable_signals = 0
        unprofitable_signals = 0

        cumulative_pnl = Decimal("0.0")
        peak_equity = Decimal("0.0")
        max_drawdown = Decimal("0.0")

        for current_point in sorted_events:
            current_key = (current_point.source_id, current_point.item_identity_hash)
            latest_prices[current_key] = current_point

            # Compare against all other sources for this item identity
            for (src, ident), other_point in latest_prices.items():
                if src == current_point.source_id or ident != current_point.item_identity_hash:
                    continue

                # Test arbitrage in both directions: buy cheaper, sell higher
                candidates = [
                    (current_point, other_point),
                    (other_point, current_point),
                ]
                signal = None
                for buy_p, sell_p in candidates:
                    sig = self.detector.evaluate_arbitrage_pair(
                        buy_point=buy_p,
                        sell_point=sell_p,
                        market_hash_name="Simulated Item",
                        liquidity_tier=LiquidityTier.HIGH,
                    )
                    if sig is not None:
                        signal = sig
                        break

                if signal is not None:
                    total_signals += 1
                    # Apply execution slippage on nominal profit
                    slippage_deduction = signal.sell_price_net * slippage_percent
                    realized_profit = signal.net_profit_nominal - slippage_deduction

                    if realized_profit > Decimal("0.0"):
                        profitable_signals += 1
                    else:
                        unprofitable_signals += 1

                    cumulative_pnl += realized_profit

                    # Update equity curve and drawdown
                    if cumulative_pnl > peak_equity:
                        peak_equity = cumulative_pnl
                    drawdown = peak_equity - cumulative_pnl
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown

        # Calculate Precision and FDR
        if total_signals > 0:
            precision = (Decimal(profitable_signals) / Decimal(total_signals)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            fdr = (Decimal("1.0") - precision).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        else:
            precision = Decimal("1.0000")
            fdr = Decimal("0.0000")

        return BacktestReport(
            total_events_processed=len(sorted_events),
            total_signals_generated=total_signals,
            profitable_signals=profitable_signals,
            unprofitable_signals=unprofitable_signals,
            precision=precision,
            false_discovery_rate=fdr,
            total_net_profit_usd=cumulative_pnl.quantize(Decimal("0.01")),
            max_drawdown_usd=max_drawdown.quantize(Decimal("0.01")),
            slippage_percent_applied=slippage_percent,
        )
