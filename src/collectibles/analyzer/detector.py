"""Cross-source arbitrage and price anomaly detection engine."""

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from collectibles.analyzer.fees import FeeCalculator
from collectibles.core.models import (
    AnomalySignal,
    AnomalyType,
    DataStatus,
    LiquidityTier,
    PricePoint,
)

logger = structlog.get_logger(__name__)


class OpportunityDetector:
    """Detects profitable, fee-adjusted cross-source arbitrage and pricing anomalies."""

    def __init__(
        self,
        fee_calculator: FeeCalculator | None = None,
        min_net_spread_percent: Decimal = Decimal("3.0"),
        min_confidence_score: Decimal = Decimal("0.7"),
    ) -> None:
        self.fee_calculator = fee_calculator or FeeCalculator()
        self.min_net_spread_percent = min_net_spread_percent
        self.min_confidence_score = min_confidence_score

    def generate_fingerprint(
        self,
        source_buy: str,
        source_sell: str,
        item_identity_hash: str,
        time_bucket_minutes: int = 15,
    ) -> str:
        """Create deterministic de-duplication fingerprint (§14)."""
        now_ts = int(datetime.now(UTC).timestamp())
        bucket = now_ts // (time_bucket_minutes * 60)
        raw = f"{source_buy}:{source_sell}:{item_identity_hash}:{bucket}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def evaluate_arbitrage_pair(
        self,
        buy_point: PricePoint,
        sell_point: PricePoint,
        market_hash_name: str,
        liquidity_tier: LiquidityTier = LiquidityTier.MEDIUM,
    ) -> AnomalySignal | None:
        """Evaluate a pair of price points from different sources for net spread profitability."""
        # 1. Quality & Status Gates (§5)
        if buy_point.status != DataStatus.FRESH or sell_point.status != DataStatus.FRESH:
            return None

        # 2. Minimum confidence gate
        min_conf = min(buy_point.confidence, sell_point.confidence)
        if min_conf < self.min_confidence_score:
            return None

        # 3. Same source cannot arbitrage itself
        if buy_point.source_id == sell_point.source_id:
            return None

        # 4. Same item identity matching
        if buy_point.item_identity_hash != sell_point.item_identity_hash:
            return None

        # 5. Liquidity check: illiquid items are excluded from signals
        if liquidity_tier == LiquidityTier.ILLIQUID:
            return None

        # 6. Fee and spread calculations (§19)
        gross_spread, net_spread, net_profit = self.fee_calculator.compute_net_spread(
            buy_platform=buy_point.source_id,
            buy_listing_price=buy_point.normalized_price,
            sell_platform=sell_point.source_id,
            sell_listing_price=sell_point.normalized_price,
        )

        if net_spread < self.min_net_spread_percent or net_profit <= Decimal("0.0"):
            return None

        # Determine trade lock risk
        buy_cfg = self.fee_calculator.get_config(buy_point.source_id)
        trade_lock_risk = buy_cfg.has_trade_lock

        fingerprint = self.generate_fingerprint(
            source_buy=buy_point.source_id,
            source_sell=sell_point.source_id,
            item_identity_hash=buy_point.item_identity_hash,
        )

        signal = AnomalySignal(
            signal_id=f"sig_{uuid.uuid4().hex[:12]}",
            anomaly_type=AnomalyType.NET_SPREAD_ARBITRAGE,
            item_identity_hash=buy_point.item_identity_hash,
            market_hash_name=market_hash_name,
            source_buy=buy_point.source_id,
            buy_price_net=self.fee_calculator.calculate_buyer_cost(
                buy_point.source_id, buy_point.normalized_price
            ),
            source_sell=sell_point.source_id,
            sell_price_net=self.fee_calculator.calculate_seller_proceeds(
                sell_point.source_id, sell_point.normalized_price
            ),
            gross_spread_percent=gross_spread,
            net_spread_percent=net_spread,
            net_profit_nominal=net_profit,
            liquidity_tier=liquidity_tier,
            confidence_score=min_conf,
            trade_lock_risk=trade_lock_risk,
            fingerprint=fingerprint,
        )

        logger.info(
            "arbitrage.opportunity_detected",
            signal_id=signal.signal_id,
            item=market_hash_name,
            net_spread=str(net_spread),
            net_profit=str(net_profit),
            source_buy=buy_point.source_id,
            source_sell=sell_point.source_id,
        )

        return signal
