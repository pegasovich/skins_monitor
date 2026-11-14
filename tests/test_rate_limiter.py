"""Unit tests for Token Bucket Rate Limiter."""

import time

import pytest

from collectibles.core.rate_limiter import InMemoryTokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_within_capacity() -> None:
    # Capacity 3, rate 1/s
    bucket = InMemoryTokenBucket(rate_per_second=1.0, capacity=3.0)

    start = time.monotonic()
    # Consuming 3 tokens should be instantaneous
    for _ in range(3):
        await bucket.acquire("api_key", tokens=1)
    duration = time.monotonic() - start

    assert duration < 0.1


@pytest.mark.asyncio
async def test_token_bucket_throttles_when_empty() -> None:
    # Capacity 1, rate 5/s (each token takes 0.2s)
    bucket = InMemoryTokenBucket(rate_per_second=5.0, capacity=1.0)

    # First token immediate
    await bucket.acquire("api_key", tokens=1)

    # Second token requires wait
    start = time.monotonic()
    await bucket.acquire("api_key", tokens=1)
    duration = time.monotonic() - start

    assert duration >= 0.15
