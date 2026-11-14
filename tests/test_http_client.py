"""Unit tests for ResilientHttpClient with Retry-After and retry mechanics."""

import httpx
import pytest
import respx

from collectibles.core.http_client import ResilientHttpClient
from collectibles.core.rate_limiter import InMemoryTokenBucket


@pytest.mark.asyncio
@respx.mock
async def test_resilient_http_client_successful_request() -> None:
    respx.get("https://api.example.com/test").respond(
        status_code=200,
        json={"status": "ok"},
    )

    client = ResilientHttpClient(base_url="https://api.example.com")
    async with client:
        resp = await client.get("/test", correlation_id="test-corr-1")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_resilient_http_client_handles_429_retry_after() -> None:
    # First response: 429 with Retry-After: 0.1
    # Second response: 200 OK
    route = respx.get("https://api.example.com/data")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.1"}),
        httpx.Response(200, json={"data": [1, 2, 3]}),
    ]

    client = ResilientHttpClient(
        base_url="https://api.example.com",
        rate_limiter=InMemoryTokenBucket(rate_per_second=20.0, capacity=10.0),
    )

    async with client:
        resp = await client.get("/data", max_attempts=3)
        assert resp.status_code == 200
        assert resp.json() == {"data": [1, 2, 3]}


@pytest.mark.asyncio
@respx.mock
async def test_resilient_http_client_retries_transient_500() -> None:
    route = respx.get("https://api.example.com/server-error")
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(200, json={"recovered": True}),
    ]

    client = ResilientHttpClient(
        base_url="https://api.example.com",
        rate_limiter=InMemoryTokenBucket(rate_per_second=20.0, capacity=10.0),
    )

    async with client:
        resp = await client.get("/server-error", max_attempts=3)
        assert resp.status_code == 200
        assert resp.json()["recovered"] is True
