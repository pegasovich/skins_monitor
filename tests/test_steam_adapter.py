"""Unit and contract tests for SteamMarketAdapter."""

from decimal import Decimal

import pytest
import respx

from collectibles.core.models import DataStatus
from collectibles.providers.steam import SteamMarketAdapter

RAW_STEAM_RESPONSE = {
    "success": True,
    "lowest_price": "$18.45",
    "volume": "1,240",
    "median_price": "$18.10",
}


def test_steam_adapter_parses_real_json() -> None:
    adapter = SteamMarketAdapter()
    point = adapter.parse_overview_to_price_point(
        market_hash_name="AK-47 | Redline (Field-Tested)",
        raw_data=RAW_STEAM_RESPONSE,
    )

    assert point is not None
    assert point.source_id == "steam"
    assert point.normalized_price == Decimal("18.45")
    assert point.status == DataStatus.FRESH
    assert point.confidence == Decimal("0.99")


def test_steam_currency_string_cleaning() -> None:
    adapter = SteamMarketAdapter()
    assert adapter._parse_currency_string("$12.50") == Decimal("12.50")
    assert adapter._parse_currency_string("1,450.00$") == Decimal("1450.00")
    assert adapter._parse_currency_string("0.25€") == Decimal("0.25")
    assert adapter._parse_currency_string("12,50") == Decimal("12.50")
    assert adapter._parse_currency_string(None) is None
    assert adapter._parse_currency_string("") is None

    assert adapter._parse_volume_string("1,420") == 1420
    assert adapter._parse_volume_string("50") == 50
    assert adapter._parse_volume_string(None) == 0


@pytest.mark.asyncio
@respx.mock
async def test_steam_fetch_item_price_network_mock() -> None:
    respx.get("https://steamcommunity.com/market/priceoverview/").respond(
        status_code=200,
        json=RAW_STEAM_RESPONSE,
    )

    adapter = SteamMarketAdapter()
    point = await adapter.fetch_item_price("AK-47 | Redline (Field-Tested)")

    assert point is not None
    assert point.source_id == "steam"
    assert point.normalized_price == Decimal("18.45")


@pytest.mark.asyncio
@respx.mock
async def test_steam_health_check() -> None:
    respx.get("https://steamcommunity.com/market/priceoverview/").respond(
        status_code=200,
        json={"success": True, "lowest_price": "$10.00"},
    )

    adapter = SteamMarketAdapter()
    assert await adapter.health_check() is True
