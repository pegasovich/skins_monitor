"""Single-cycle smoke test against live public endpoints in DRY_RUN mode."""

import asyncio

import structlog

from collectibles.core.config import settings
from collectibles.main import CollectiblesMonitorOrchestrator

logger = structlog.get_logger(__name__)


async def main() -> None:
    print("\n" + "=" * 60)
    print("🚀 STARTING CS2 LIVE SMOKE TEST (1 CYCLE, DRY_RUN=TRUE)")
    print(f"Environment: {settings.environment} | Base Currency: {settings.base_currency}")
    print("=" * 60 + "\n")

    orchestrator = CollectiblesMonitorOrchestrator()
    await orchestrator.initialize()

    active_providers = orchestrator.registry.list_active()
    print(f"Active providers registered: {[p.provider_id for p in active_providers]}\n")

    print("📡 Fetching real listings from live marketplace APIs...")
    await orchestrator.run_cycle()

    print("\n" + "=" * 60)
    print("✅ SMOKE TEST COMPLETED SUCCESSFULLY!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
