"""Unit tests for CollectiblesMonitorOrchestrator."""

import pytest

from collectibles.main import CollectiblesMonitorOrchestrator
from collectibles.storage.repository import SQLiteStorageRepository


@pytest.mark.asyncio
async def test_orchestrator_initialization_and_single_cycle(tmp_path) -> None:
    orchestrator = CollectiblesMonitorOrchestrator()
    # Use temporary sqlite db to prevent polluting workspace
    db_file = str(tmp_path / "orchestrator_test.db")
    orchestrator.storage = SQLiteStorageRepository(db_path=db_file)

    await orchestrator.initialize()

    # Providers registered
    assert len(orchestrator.registry.list_active()) == 1

    # Run single cycle
    await orchestrator.run_cycle()

    # Graceful stop
    orchestrator.stop()
    assert orchestrator.running is False
