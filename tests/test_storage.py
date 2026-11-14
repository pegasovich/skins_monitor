"""Tests for SQLite Storage Repository."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collectibles.core.models import DataStatus, PricePoint
from collectibles.storage.repository import SQLiteStorageRepository


@pytest.mark.asyncio
async def test_sqlite_repository_lifecycle(tmp_path) -> None:
    db_file = str(tmp_path / "test.db")
    repo = SQLiteStorageRepository(db_path=db_file)
    await repo.initialize()

    point = PricePoint(
        source_id="csfloat",
        external_item_id="12345",
        item_identity_hash="hash_abc",
        raw_price=Decimal("45.50"),
        raw_currency="USD",
        normalized_price=Decimal("45.50"),
        base_currency="USD",
        event_time=datetime.now(UTC),
        status=DataStatus.FRESH,
        confidence=Decimal("0.98"),
        correlation_id="corr-test",
    )

    await repo.save_price_point(point)

    fetched = await repo.get_latest_price("csfloat", "hash_abc")
    assert fetched is not None
    assert fetched.external_item_id == "12345"
    assert fetched.normalized_price == Decimal("45.50")
    assert fetched.confidence == Decimal("0.98")
    assert fetched.status == DataStatus.FRESH
