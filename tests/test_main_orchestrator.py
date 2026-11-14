"""Unit tests for CollectiblesMonitorOrchestrator."""

import pytest
import respx

from collectibles.main import CollectiblesMonitorOrchestrator
from collectibles.storage.repository import SQLiteStorageRepository


@pytest.mark.asyncio
@respx.mock
async def test_orchestrator_initialization_and_single_cycle(tmp_path) -> None:
    raw_csfloat = {
        "id": "csf_listing_1",
        "price": 1000,
        "item": {
            "market_hash_name": "AK-47 | Redline (Field-Tested)",
            "stickers": [],
        },
    }
    raw_skinport = [
        {
            "market_hash_name": "AK-47 | Redline (Field-Tested)",
            "currency": "USD",
            "suggested_price": 25.0,
            "min_price": 20.0,
            "quantity": 5,
        }
    ]

    respx.get("https://csfloat.com/api/v1/listings").respond(status_code=200, json=[raw_csfloat])
    respx.get("https://api.skinport.com/v1/items").respond(status_code=200, json=raw_skinport)
    respx.get("https://steamcommunity.com/market/priceoverview/").respond(
        status_code=200, json={"success": True, "lowest_price": "$22.00"}
    )

    orchestrator = CollectiblesMonitorOrchestrator()
    # Use temporary sqlite db to prevent polluting workspace
    db_file = str(tmp_path / "orchestrator_test.db")
    orchestrator.storage = SQLiteStorageRepository(db_path=db_file)

    await orchestrator.initialize()

    # Three live providers registered: csfloat, skinport, steam
    assert len(orchestrator.registry.list_active()) == 3

    # Run single cycle with arbitrage matching
    await orchestrator.run_cycle()

    # Graceful stop
    orchestrator.stop()
    assert orchestrator.running is False
