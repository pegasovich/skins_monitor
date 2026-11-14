"""Unit tests for CollectiblesMonitorOrchestrator."""

import pytest
import respx

from collectibles.main import CollectiblesMonitorOrchestrator
from collectibles.storage.repository import SQLiteStorageRepository


@pytest.mark.asyncio
@respx.mock
async def test_orchestrator_initialization_and_single_cycle(tmp_path) -> None:
    respx.get("https://csfloat.com/api/v1/listings").respond(status_code=200, json=[])
    respx.get("https://api.skinport.com/v1/items").respond(status_code=200, json=[])
    respx.get("https://steamcommunity.com/market/priceoverview/").respond(
        status_code=200, json={"success": False}
    )

    orchestrator = CollectiblesMonitorOrchestrator()
    # Use temporary sqlite db to prevent polluting workspace
    db_file = str(tmp_path / "orchestrator_test.db")
    orchestrator.storage = SQLiteStorageRepository(db_path=db_file)

    await orchestrator.initialize()

    # Three live providers registered: csfloat, skinport, steam
    assert len(orchestrator.registry.list_active()) == 3

    # Run single cycle
    await orchestrator.run_cycle()

    # Graceful stop
    orchestrator.stop()
    assert orchestrator.running is False
