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

    orchestrator = CollectiblesMonitorOrchestrator()
    # Use temporary sqlite db to prevent polluting workspace
    db_file = str(tmp_path / "orchestrator_test.db")
    orchestrator.storage = SQLiteStorageRepository(db_path=db_file)

    await orchestrator.initialize()

    # Both live providers registered
    assert len(orchestrator.registry.list_active()) == 2

    # Run single cycle
    await orchestrator.run_cycle()

    # Graceful stop
    orchestrator.stop()
    assert orchestrator.running is False
