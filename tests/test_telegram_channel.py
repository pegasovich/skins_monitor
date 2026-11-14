"""Unit tests for TelegramAlertChannel."""

from decimal import Decimal

import pytest
import respx
from pydantic import SecretStr

from collectibles.alerts.telegram import TelegramAlertChannel
from collectibles.core.models import (
    AnomalySignal,
    AnomalyType,
    LiquidityTier,
)


def sample_signal() -> AnomalySignal:
    return AnomalySignal(
        signal_id="sig_test_123",
        anomaly_type=AnomalyType.NET_SPREAD_ARBITRAGE,
        item_identity_hash="item_hash_abc",
        market_hash_name="AK-47 | Asiimov (Field-Tested)",
        source_buy="csfloat",
        buy_price_net=Decimal("50.00"),
        source_sell="skinport",
        sell_price_net=Decimal("65.00"),
        gross_spread_percent=Decimal("30.00"),
        net_spread_percent=Decimal("22.50"),
        net_profit_nominal=Decimal("15.00"),
        liquidity_tier=LiquidityTier.HIGH,
        confidence_score=Decimal("0.95"),
        trade_lock_risk=True,
        fingerprint="fp_test_123",
    )


@pytest.mark.asyncio
async def test_telegram_channel_dry_run_does_not_call_network() -> None:
    channel = TelegramAlertChannel(
        bot_token=SecretStr("fake_token_123"),
        chat_id="12345678",
        dry_run=True,
    )
    sig = sample_signal()

    # In dry-run, method returns True without making actual HTTP request
    delivered = await channel.send_signal(sig)
    assert delivered is True

    html = channel.format_signal_html(sig)
    assert "[DRY_RUN SIMULATION]" in html
    assert "AK-47 | Asiimov" in html
    assert "+22.5" in html


@pytest.mark.asyncio
@respx.mock
async def test_telegram_channel_live_dispatch() -> None:
    respx.post("https://api.telegram.org/botlive_token/sendMessage").respond(
        status_code=200,
        json={"ok": True, "result": {"message_id": 999}},
    )

    channel = TelegramAlertChannel(
        bot_token=SecretStr("live_token"),
        chat_id="12345678",
        dry_run=False,
    )
    sig = sample_signal()

    delivered = await channel.send_signal(sig)
    assert delivered is True
