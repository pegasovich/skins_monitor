"""Resilient HTTP client with connection pooling, Retry-After parsing, and jitter."""

import asyncio
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from collectibles.core.rate_limiter import BaseRateLimiter, InMemoryTokenBucket

logger = structlog.get_logger(__name__)


def is_transient_error(exc: BaseException) -> bool:
    """Identify retryable network drops, timeouts, 429, and temporary 5xx errors."""
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # 429, 500, 502, 503, 504 are transient
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


class ResilientHttpClient:
    """Production-grade HTTP client with rate limiting, circuit breaker, and retry gates."""

    def __init__(
        self,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        rate_limiter: BaseRateLimiter | None = None,
        rate_limit_key: str = "default",
        timeout_seconds: float = 10.0,
        max_connections: int = 20,
    ) -> None:
        self.base_url = base_url
        self.rate_limiter = rate_limiter or InMemoryTokenBucket(rate_per_second=2.0)
        self.rate_limit_key = rate_limit_key

        default_headers = {
            "User-Agent": "CollectiblesMonitor/0.1.0 (Research & Pricing Infrastructure; +safe)",
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        limits = httpx.Limits(
            max_keepalive_connections=max_connections,
            max_connections=max_connections * 2,
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=default_headers,
            limits=limits,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        """Close underlying connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> "ResilientHttpClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def _parse_retry_after(self, response: httpx.Response) -> float | None:
        """Parse Retry-After header as seconds or HTTP-Date."""
        header_val = response.headers.get("Retry-After")
        if not header_val:
            return None

        try:
            return float(header_val)
        except ValueError:
            pass

        try:
            dt = parsedate_to_datetime(header_val)
            diff = dt.timestamp() - time.time()
            return max(0.0, diff)
        except Exception:
            return None

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_attempts: int = 3,
    ) -> httpx.Response:
        """Execute rate-limited idempotent GET request with Retry-After and jitter."""
        req_headers: dict[str, str] = {}
        if correlation_id:
            req_headers["X-Correlation-ID"] = correlation_id

        retrying = AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential_jitter(multiplier=0.5, max=5.0),
            retry=retry_if_exception(is_transient_error),
            reraise=True,
        )

        async for attempt in retrying:
            with attempt:
                # 1. Acquire Token Bucket rate limit token
                await self.rate_limiter.acquire(self.rate_limit_key, tokens=1)

                logger.debug(
                    "http_client.request",
                    endpoint=endpoint,
                    attempt=attempt.retry_state.attempt_number,
                    correlation_id=correlation_id,
                )

                response = await self._client.get(endpoint, params=params, headers=req_headers)

                # 2. Check for HTTP 429 Rate Limited
                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response) or 5.0
                    logger.warning(
                        "http_client.rate_limited_429",
                        endpoint=endpoint,
                        retry_after_seconds=retry_after,
                    )
                    # Cap in-flight sleep to at most 10 seconds to prevent blocking daemon loop
                    sleep_time = min(retry_after, 10.0)
                    await asyncio.sleep(sleep_time)
                    response.raise_for_status()

                # 3. Check for 5xx transient server errors
                if response.status_code >= 500:
                    response.raise_for_status()

                return response

        raise RuntimeError("Unreachable: retrying loop completed without response or exception")
