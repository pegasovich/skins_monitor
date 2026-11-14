"""Main application orchestrator and daemon loop."""

import asyncio
import signal
import sys
from decimal import Decimal

import structlog

from collectibles.alerts.engine import AlertChannel, AlertEngine, ConsoleAlertChannel
from collectibles.alerts.telegram import TelegramAlertChannel
from collectibles.analyzer.detector import OpportunityDetector
from collectibles.core.config import settings
from collectibles.core.models import PricePoint
from collectibles.providers.base import ProviderRegistry
from collectibles.providers.csfloat import CSFloatLiveAdapter
from collectibles.providers.skinport import SkinportLiveAdapter
from collectibles.providers.steam import SteamMarketAdapter
from collectibles.storage.repository import SQLiteStorageRepository

logger = structlog.get_logger(__name__)


class CollectiblesMonitorOrchestrator:
    """Coordinates ingestion, analysis, persistence, and alert dispatch."""

    def __init__(self) -> None:
        self.running = False
        self._cycle_number: int = 0
        self.storage = SQLiteStorageRepository()
        self.detector = OpportunityDetector(
            min_net_spread_percent=Decimal(str(settings.min_net_spread_pct))
        )
        self.registry = ProviderRegistry()

        # Alert channels setup
        channels: list[AlertChannel] = [ConsoleAlertChannel()]
        if settings.telegram_bot_token and settings.telegram_chat_id:
            channels.append(
                TelegramAlertChannel(
                    bot_token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                    dry_run=settings.dry_run,
                )
            )
        self.alert_engine = AlertEngine(settings=settings, channels=channels)

    async def initialize(self) -> None:
        """Initialize storage and register providers."""
        logger.info(
            "orchestrator.starting",
            dry_run=settings.dry_run,
            environment=settings.environment,
            stop_all_outbound=settings.stop_all_outbound,
        )
        await self.storage.initialize()

        # Register live providers
        csfloat_key = (
            settings.csfloat_api_key.get_secret_value() if settings.csfloat_api_key else None
        )
        skinport_secret = (
            settings.skinport_client_secret.get_secret_value()
            if settings.skinport_client_secret
            else None
        )
        self.registry.register(CSFloatLiveAdapter(api_key=csfloat_key, provider_id="csfloat"))
        self.registry.register(
            SkinportLiveAdapter(
                client_id=settings.skinport_client_id,
                client_secret=skinport_secret,
                provider_id="skinport",
            )
        )
        self.registry.register(SteamMarketAdapter(provider_id="steam"))

    async def run_cycle(self) -> None:
        """Single ingestion and analysis iteration."""
        self._cycle_number += 1
        active_providers = self.registry.list_active()
        logger.info(
            "orchestrator.cycle_start",
            cycle=self._cycle_number,
            active_providers=len(active_providers),
        )

        collected_points: list[PricePoint] = []
        hot_targets: list[str] = []

        # 1. Fetch from skinport first to discover hot discounted candidates
        skinport_prov = self.registry.get("skinport")
        if skinport_prov and isinstance(skinport_prov, SkinportLiveAdapter):
            try:
                sp_points = await skinport_prov.fetch_listings(limit=50)
                collected_points.extend(sp_points)
                hot_targets = skinport_prov.hot_candidates[:12]
            except Exception as e:
                logger.error("orchestrator.skinport_fetch_failed", error=str(e))

        # 2. Fetch other providers (passing hot_targets to Steam and CSFloat for targeted arbitrage)
        for provider in active_providers:
            if provider.provider_id == "skinport":
                continue
            try:
                if provider.provider_id == "steam" and isinstance(provider, SteamMarketAdapter):
                    points = await provider.fetch_listings(limit=5, target_items=hot_targets)
                elif provider.provider_id == "csfloat" and isinstance(provider, CSFloatLiveAdapter):
                    # Targeted: search CSFloat for the same hot items Skinport is discounting
                    if hot_targets:
                        points = await provider.fetch_listings(
                            limit=50, target_items=hot_targets[:10]
                        )
                    else:
                        points = await provider.fetch_listings(limit=50)
                else:
                    points = await provider.fetch_listings(limit=50)
                collected_points.extend(points)
            except Exception as e:
                logger.error(
                    "orchestrator.provider_fetch_failed",
                    provider=provider.provider_id,
                    error=str(e),
                )

        # Persist observations
        for pt in collected_points:
            await self.storage.save_price_point(pt)

        # Cross-source arbitrage evaluation
        by_hash: dict[str, list[PricePoint]] = {}
        for pt in collected_points:
            by_hash.setdefault(pt.item_identity_hash, []).append(pt)

        # Diagnostic: log how many hashes have multi-source coverage
        multi_source = {h: ps for h, ps in by_hash.items() if len({p.source_id for p in ps}) >= 2}
        logger.info(
            "orchestrator.hash_coverage",
            total_unique_hashes=len(by_hash),
            multi_source_matches=len(multi_source),
            sources_per_hash_sample={
                h[:8]: [p.source_id for p in ps] for h, ps in list(multi_source.items())[:5]
            },
        )

        signals_found = 0
        for ident_hash, pts in by_hash.items():
            if len(pts) >= 2:
                # Compare pairs across different sources
                for i in range(len(pts)):
                    for j in range(i + 1, len(pts)):
                        p1, p2 = pts[i], pts[j]
                        if p1.source_id == p2.source_id:
                            continue
                        # Test both directions
                        for buy_p, sell_p in [(p1, p2), (p2, p1)]:
                            item_name = (
                                buy_p.market_hash_name
                                or sell_p.market_hash_name
                                or f"CS2 Skin #{ident_hash[:8]}"
                            )
                            signal = self.detector.evaluate_arbitrage_pair(
                                buy_point=buy_p,
                                sell_point=sell_p,
                                market_hash_name=item_name,
                            )
                            if signal:
                                signals_found += 1
                                await self.alert_engine.dispatch(signal)

        logger.info(
            "orchestrator.cycle_complete",
            cycle=self._cycle_number,
            points_collected=len(collected_points),
            signals_found=signals_found,
        )

    async def start(self) -> None:
        """Run continuous monitoring loop until cancelled."""
        self.running = True
        await self.initialize()

        logger.info("orchestrator.running_loop_started")
        while self.running:
            try:
                await self.run_cycle()
                # Poll interval: 15s pause to respect market rate limits
                await asyncio.sleep(15.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("orchestrator.unexpected_error", error=str(e))
                await asyncio.sleep(2.0)

        logger.info("orchestrator.stopped_gracefully")

    def stop(self) -> None:
        """Trigger graceful termination."""
        self.running = False


async def async_main() -> None:
    orchestrator = CollectiblesMonitorOrchestrator()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, orchestrator.stop)

    await orchestrator.start()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("orchestrator.interrupted_by_user")


if __name__ == "__main__":
    main()
