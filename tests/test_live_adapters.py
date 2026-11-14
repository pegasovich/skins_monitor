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
    adapter = CSFloatLiveAdapter()
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

    adapter = CSFloatLiveAdapter()
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
