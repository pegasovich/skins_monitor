"""Alerting engine with deduplication, throttling, and safety kill-switch."""

import time
from typing import Protocol

import structlog

from collectibles.core.config import Settings
from collectibles.core.config import settings as global_settings
from collectibles.core.models import AnomalySignal

logger = structlog.get_logger(__name__)


class AlertChannel(Protocol):
    """Protocol for dispatching notification messages."""

    async def send(self, message: str) -> bool:
        """Send message and return delivery status."""
        ...

    async def send_signal(self, signal: AnomalySignal) -> bool:
        """Send rich formatted signal with interactive UI."""
        ...


class ConsoleAlertChannel:
    """Standard console logger channel for simulation and dry-run output."""

    async def send(self, message: str) -> bool:
        logger.info("alert_channel.console_dispatch", message=message)
        return True

    async def send_signal(self, signal: AnomalySignal) -> bool:
        logger.info(
            "alert_channel.console_signal_dispatch",
            signal_id=signal.signal_id,
            item=signal.market_hash_name,
        )
        return True


class AlertEngine:
    """Manages dispatch, deduplication, and safety gates for anomaly signals."""

    def __init__(
        self,
        settings: Settings | None = None,
        channels: list[AlertChannel] | None = None,
        dedup_window_seconds: int = 900,  # 15 minutes
    ) -> None:
        self.settings = settings or global_settings
        self.channels = channels or [ConsoleAlertChannel()]
        self.dedup_window_seconds = dedup_window_seconds
        # In-memory deduplication cache for Phase 1 (Redis in Phase 3)
        self._sent_fingerprints: dict[str, float] = {}

    def _cleanup_expired_fingerprints(self, now: float) -> None:
        """Remove entries older than 2x the dedup window (§14)."""
        cutoff = now - (self.dedup_window_seconds * 2)
        self._sent_fingerprints = {
            fp: ts for fp, ts in self._sent_fingerprints.items() if ts >= cutoff
        }

    def is_duplicate(self, fingerprint: str) -> bool:
        """Check if fingerprint was recently dispatched."""
        now = time.time()
        self._cleanup_expired_fingerprints(now)
        last_sent = self._sent_fingerprints.get(fingerprint)
        if last_sent is not None and (now - last_sent) < self.dedup_window_seconds:
            return True
        return False

    def mark_dispatched(self, fingerprint: str) -> None:
        """Record fingerprint timestamp."""
        self._sent_fingerprints[fingerprint] = time.time()

    def format_signal_message(self, signal: AnomalySignal) -> str:
        """Render high-transparency alert message."""
        mode_prefix = "[DRY_RUN]" if self.settings.dry_run else "[LIVE]"
        trade_lock_warn = (
            "⚠️ 7-Day Trade Lock Required" if signal.trade_lock_risk else "✅ Instant Tradeable"
        )

        return (
            f"{mode_prefix} 🎯 ARBITRAGE OPPORTUNITY DETECTED\n"
            f"Item: {signal.market_hash_name}\n"
            f"Buy on: {signal.source_buy.upper()} at ${signal.buy_price_net}\n"
            f"Sell on: {signal.source_sell.upper()} (Net Proceeds: ${signal.sell_price_net})\n"
            f"Gross Spread: {signal.gross_spread_percent}%\n"
            f"Net Spread (After Platform Fees): {signal.net_spread_percent}%\n"
            f"Net Estimated Profit: +${signal.net_profit_nominal}\n"
            f"Liquidity Tier: {signal.liquidity_tier.value}\n"
            f"Confidence: {signal.confidence_score}\n"
            f"Status: {trade_lock_warn}\n"
            f"Signal ID: {signal.signal_id}"
        )

    async def dispatch(self, signal: AnomalySignal) -> bool:
        """Process signal through safety gates and dispatch to configured channels."""
        # Safety Gate 1: Global Kill-Switch (§7)
        if self.settings.stop_all_outbound:
            logger.warning("alert_engine.blocked_by_kill_switch", signal_id=signal.signal_id)
            return False

        # Safety Gate 2: Deduplication (§14)
        if self.is_duplicate(signal.fingerprint):
            logger.debug("alert_engine.deduplicated", fingerprint=signal.fingerprint)
            return False

        message = self.format_signal_message(signal)

        # Safety Gate 3: DRY_RUN (§0, §11)
        if self.settings.dry_run:
            logger.info("alert_engine.dry_run_suppressed_live_dispatch", signal_id=signal.signal_id)
            # In dry-run, we route strictly to safe/console channels
            for ch in self.channels:
                if isinstance(ch, ConsoleAlertChannel):
                    await ch.send(message)
            self.mark_dispatched(signal.fingerprint)
            return True

        # LIVE Mode: Dispatch to all registered channels
        success = True
        for ch in self.channels:
            if hasattr(ch, "send_signal"):
                delivered = await ch.send_signal(signal)
            else:
                delivered = await ch.send(message)
            if not delivered:
                success = False

        if success:
            self.mark_dispatched(signal.fingerprint)
            logger.info("alert_engine.live_dispatched", signal_id=signal.signal_id)

        return success
