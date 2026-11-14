"""Send a test rich Telegram signal to verify channel connectivity."""

import asyncio
from decimal import Decimal

import structlog

from collectibles.alerts.telegram import TelegramAlertChannel
from collectibles.core.config import Settings
from collectibles.core.models import (
    AnomalySignal,
    AnomalyType,
    LiquidityTier,
)

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = Settings()
    print("\n--- Testing Telegram Alert Channel ---")
    print(f"Chat ID: {settings.telegram_chat_id}")
    has_token = bool(settings.telegram_bot_token)
    print(f"Token Configured: {has_token}")

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("❌ Error: Bot token or Chat ID is missing in .env")
        return

    channel = TelegramAlertChannel(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        dry_run=False,  # Live dispatch to user
    )

    # Example real skin scenario
    sample = AnomalySignal(
        signal_id="sig_live_demo_001",
        anomaly_type=AnomalyType.NET_SPREAD_ARBITRAGE,
        item_identity_hash="demo_hash_ak47_redline",
        market_hash_name="AK-47 | Redline (Field-Tested)",
        source_buy="skinport",
        buy_price_net=Decimal("15.20"),
        source_sell="steam",
        sell_price_net=Decimal("18.45"),
        gross_spread_percent=Decimal("21.38"),
        net_spread_percent=Decimal("13.62"),
        net_profit_nominal=Decimal("2.07"),
        liquidity_tier=LiquidityTier.ULTRA_HIGH,
        confidence_score=Decimal("0.99"),
        trade_lock_risk=False,
        fingerprint="demo_fp_001",
    )

    print("📤 Sending rich interactive signal to Telegram...")
    success = await channel.send_signal(sample)

    if success:
        print("🎉 SUCCESS! Check your Telegram, the signal message has been delivered!")
    else:
        print("❌ Delivery failed. Make sure you pressed /start in your bot first.")


if __name__ == "__main__":
    asyncio.run(main())
