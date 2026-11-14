"""Storage repository for persisting price points and anomaly signals."""

import abc
from decimal import Decimal

import aiosqlite

from collectibles.core.models import AnomalySignal, PricePoint


class BaseStorageRepository(abc.ABC):
    """Abstract interface for price point time-series storage."""

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Create tables/indexes if not exist."""

    @abc.abstractmethod
    async def save_price_point(self, point: PricePoint) -> None:
        """Insert a price observation."""

    @abc.abstractmethod
    async def save_signal(self, signal: AnomalySignal) -> None:
        """Insert a detected anomaly signal."""

    @abc.abstractmethod
    async def get_latest_price(self, source_id: str, item_identity_hash: str) -> PricePoint | None:
        """Retrieve most recent observation for item on source."""


class SQLiteStorageRepository(BaseStorageRepository):
    """Local SQLite implementation for Phase 1 MVP."""

    def __init__(self, db_path: str = "collectibles.db") -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS price_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_item_id TEXT NOT NULL,
                    item_identity_hash TEXT NOT NULL,
                    raw_price TEXT NOT NULL,
                    raw_currency TEXT NOT NULL,
                    normalized_price TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    correlation_id TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_price_points_lookup
                ON price_points(item_identity_hash, source_id, event_time)
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS anomaly_signals (
                    signal_id TEXT PRIMARY KEY,
                    anomaly_type TEXT NOT NULL,
                    item_identity_hash TEXT NOT NULL,
                    market_hash_name TEXT NOT NULL,
                    source_buy TEXT NOT NULL,
                    buy_price_net TEXT NOT NULL,
                    source_sell TEXT NOT NULL,
                    sell_price_net TEXT NOT NULL,
                    gross_spread_percent TEXT NOT NULL,
                    net_spread_percent TEXT NOT NULL,
                    net_profit_nominal TEXT NOT NULL,
                    liquidity_tier TEXT NOT NULL,
                    confidence_score TEXT NOT NULL,
                    trade_lock_risk INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def save_price_point(self, point: PricePoint) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO price_points (
                    source_id, external_item_id, item_identity_hash,
                    raw_price, raw_currency, normalized_price, base_currency,
                    event_time, fetched_at, status, confidence, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.source_id,
                    point.external_item_id,
                    point.item_identity_hash,
                    str(point.raw_price),
                    point.raw_currency,
                    str(point.normalized_price),
                    point.base_currency,
                    point.event_time.isoformat(),
                    point.fetched_at.isoformat(),
                    point.status.value,
                    str(point.confidence),
                    point.correlation_id,
                ),
            )
            await db.commit()

    async def save_signal(self, signal: AnomalySignal) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO anomaly_signals (
                    signal_id, anomaly_type, item_identity_hash, market_hash_name,
                    source_buy, buy_price_net, source_sell, sell_price_net,
                    gross_spread_percent, net_spread_percent, net_profit_nominal,
                    liquidity_tier, confidence_score, trade_lock_risk, created_at, fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.anomaly_type.value,
                    signal.item_identity_hash,
                    signal.market_hash_name,
                    signal.source_buy,
                    str(signal.buy_price_net),
                    signal.source_sell,
                    str(signal.sell_price_net),
                    str(signal.gross_spread_percent),
                    str(signal.net_spread_percent),
                    str(signal.net_profit_nominal),
                    signal.liquidity_tier.value,
                    str(signal.confidence_score),
                    1 if signal.trade_lock_risk else 0,
                    signal.created_at.isoformat(),
                    signal.fingerprint,
                ),
            )
            await db.commit()

    async def get_latest_price(self, source_id: str, item_identity_hash: str) -> PricePoint | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM price_points
                WHERE source_id = ? AND item_identity_hash = ?
                ORDER BY event_time DESC LIMIT 1
                """,
                (source_id, item_identity_hash),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            from datetime import datetime

            from collectibles.core.models import DataStatus

            return PricePoint(
                source_id=row["source_id"],
                external_item_id=row["external_item_id"],
                item_identity_hash=row["item_identity_hash"],
                raw_price=Decimal(row["raw_price"]),
                raw_currency=row["raw_currency"],
                normalized_price=Decimal(row["normalized_price"]),
                base_currency=row["base_currency"],
                event_time=datetime.fromisoformat(row["event_time"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                status=DataStatus(row["status"]),
                confidence=Decimal(row["confidence"]),
                correlation_id=row["correlation_id"],
            )
