"""Unit and contract tests for CSFloat and Skinport live adapters."""

from decimal import Decimal

import pytest
import respx

from collectibles.core.models import DataStatus
from collectibles.providers.csfloat import CSFloatLiveAdapter
from collectibles.providers.skinport import SkinportLiveAdapter

RAW_CSFLOAT_LISTING = {
    "id": "csf_listing_987",
    "price": 14500,  # $145.00
    "created_at": "2026-11-14T15:30:00Z",
    "item": {
        "market_hash_name": "AK-47 | Vulcan (Field-Tested)",
        "float_value": 0.1854,
        "paint_seed": 456,
        "paint_index": 302,
        "is_stattrak": False,
        "is_souvenir": False,
        "stickers": [{"slot": 0, "name": "Cloud9 | Katowice 2015", "wear": 0.05}],
    },
}

RAW_SKINPORT_ITEM = {
    "market_hash_name": "AK-47 | Vulcan (Field-Tested)",
    "currency": "USD",
    "suggested_price": 160.50,
    "min_price": 158.00,
    "max_price": 175.00,
    "quantity": 14,
    "updated_at": 1731600000,
}


def test_csfloat_adapter_parses_real_json() -> None:
    adapter = CSFloatLiveAdapter(api_key="mock_csfloat_key")
    point = adapter.parse_listing_to_price_point(RAW_CSFLOAT_LISTING)

    assert point.source_id == "csfloat"
    assert point.external_item_id == "csf_listing_987"
    assert point.normalized_price == Decimal("145.00")
    assert point.status == DataStatus.FRESH
    assert point.confidence == Decimal("0.98")


def test_skinport_adapter_parses_real_json() -> None:
    adapter = SkinportLiveAdapter()
    point = adapter.parse_item_to_price_point(RAW_SKINPORT_ITEM)

    assert point is not None
    assert point.source_id == "skinport"
    assert point.normalized_price == Decimal("158.00")
    assert point.status == DataStatus.FRESH


@pytest.mark.asyncio
@respx.mock
async def test_csfloat_fetch_listings_network_mock() -> None:
    respx.get("https://csfloat.com/api/v1/listings").respond(
        status_code=200,
        json=[RAW_CSFLOAT_LISTING],
    )

    adapter = CSFloatLiveAdapter(api_key="mock_csfloat_key")
    listings = await adapter.fetch_listings(limit=10)

    assert len(listings) == 1
    assert listings[0].normalized_price == Decimal("145.00")


@pytest.mark.asyncio
@respx.mock
async def test_skinport_fetch_listings_network_mock() -> None:
    respx.get("https://api.skinport.com/v1/items").respond(
        status_code=200,
        json=[RAW_SKINPORT_ITEM],
    )

    adapter = SkinportLiveAdapter()
    items = await adapter.fetch_listings(limit=10)

    assert len(items) == 1
    assert items[0].normalized_price == Decimal("158.00")


@pytest.mark.asyncio
@respx.mock
async def test_adapters_health_checks() -> None:
    respx.get("https://csfloat.com/api/v1/listings").respond(status_code=200, json=[])
    respx.get("https://api.skinport.com/v1/items").respond(status_code=200, json=[])

    csfloat = CSFloatLiveAdapter()
    skinport = SkinportLiveAdapter()

    assert await csfloat.health_check() is True
    assert await skinport.health_check() is True


@pytest.mark.asyncio
@respx.mock
async def test_steam_adapter_and_cache() -> None:
    from collectibles.providers.steam import SteamMarketAdapter

    respx.get("https://steamcommunity.com/market/priceoverview/").respond(
        status_code=200,
        json={"success": True, "lowest_price": "$25.50", "median_price": "$24.00"},
    )

    steam = SteamMarketAdapter()
    pt = await steam.fetch_item_price("AK-47 | Redline (Field-Tested)")
    assert pt is not None
    assert pt.normalized_price == Decimal("25.50")

    # Second call should hit in-memory price cache without network request
    pt_cached = await steam.fetch_item_price("AK-47 | Redline (Field-Tested)")
    assert pt_cached is not None
    assert pt_cached.normalized_price == Decimal("25.50")


@pytest.mark.asyncio
@respx.mock
async def test_csfloat_alternating_sort_and_custom_sticker_slot() -> None:
    listing_with_slot_5 = {
        "id": "csf_listing_custom_slot",
        "price": 2500,
        "item": {
            "market_hash_name": "AK-47 | Slate (Field-Tested)",
            "stickers": [{"slot": 5, "name": "Custom Sticker"}],
        },
    }

    respx.get("https://csfloat.com/api/v1/listings").respond(
        status_code=200,
        json=[listing_with_slot_5],
    )

    adapter = CSFloatLiveAdapter(api_key="mock_key")
    # First call: most_recent
    res1 = await adapter.fetch_listings(limit=5)
    assert len(res1) == 1
    assert adapter._toggle_sort is True

    # Second call: highest_discount
    res2 = await adapter.fetch_listings(limit=5)
    assert len(res2) == 1
    assert adapter._toggle_sort is False


def test_csfloat_adapter_rejects_overpriced_listings() -> None:
    adapter = CSFloatLiveAdapter(api_key="mock_csfloat_key")
    overpriced_listing = {
        "id": "csf_overpriced_1",
        "price": 79102,  # $791.02
        "reference": {"base_price": 64000, "predicted_price": 64000},  # market is $640.00
        "item": {
            "market_hash_name": "★ M9 Bayonet | Slaughter (Factory New)",
            "float_value": 0.041,
        },
    }
    point = adapter.parse_listing_to_price_point(overpriced_listing)
    assert point is None  # Must reject overpriced ask!


def test_skinport_adapter_parses_eur_currency() -> None:
    adapter = SkinportLiveAdapter()
    eur_item = {
        "market_hash_name": "★ M9 Bayonet | Slaughter (Factory New)",
        "currency": "EUR",
        "suggested_price": 799.33,
        "min_price": 635.62,
        "quantity": 1,
    }
    point = adapter.parse_item_to_price_point(eur_item)
    assert point is not None
    assert point.raw_price == Decimal("635.62")
    assert point.raw_currency == "EUR"
    # Normalizes to USD using eur_usd_rate (default 1.08)
    assert point.normalized_price == Decimal("686.47")


@pytest.mark.asyncio
@respx.mock
async def test_telegram_channel_send_signal_mock() -> None:
    from datetime import UTC, datetime

    from pydantic import SecretStr

    from collectibles.alerts.telegram import TelegramAlertChannel
    from collectibles.core.models import AnomalySignal, LiquidityTier

    respx.post("https://api.telegram.org/botmock_token/sendMessage").respond(
        status_code=200,
        json={"ok": True},
    )

    ch = TelegramAlertChannel(
        bot_token=SecretStr("mock_token"),
        chat_id="123456",
        dry_run=False,
    )

    signal = AnomalySignal(
        signal_id="sig_test_123",
        anomaly_type="net_spread_arbitrage",
        item_identity_hash="hash_test",
        market_hash_name="AK-47 | Redline (Field-Tested)",
        source_buy="csfloat",
        source_sell="steam",
        buy_price_net=Decimal("15.00"),
        sell_price_net=Decimal("20.00"),
        gross_spread_percent=Decimal("33.33"),
        net_spread_percent=Decimal("25.00"),
        net_profit_nominal=Decimal("5.00"),
        liquidity_tier=LiquidityTier.HIGH,
        confidence_score=Decimal("0.95"),
        fingerprint="fp_123",
        trade_lock_risk=False,
        detected_at=datetime.now(UTC),
    )

    sent = await ch.send_signal(signal)
    assert sent is True
