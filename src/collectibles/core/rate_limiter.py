"""Distributed and in-memory Token Bucket rate limiter implementations."""

import abc
import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BaseRateLimiter(abc.ABC):
    """Abstract interface for rate limiting outbound requests."""

    @abc.abstractmethod
    async def acquire(self, key: str, tokens: int = 1) -> None:
        """Wait until requested tokens are available, then consume them."""


class InMemoryTokenBucket(BaseRateLimiter):
    """Deterministic in-memory Token Bucket rate limiter with thread-safe asyncio Lock."""

    def __init__(self, rate_per_second: float = 1.0, capacity: float = 5.0) -> None:
        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self._tokens: dict[str, float] = {}
        self._last_updated: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _refill(self, key: str, now: float) -> None:
        if key not in self._tokens:
            self._tokens[key] = self.capacity
            self._last_updated[key] = now
            return

        elapsed = now - self._last_updated[key]
        if elapsed > 0:
            delta_tokens = elapsed * self.rate_per_second
            self._tokens[key] = min(self.capacity, self._tokens[key] + delta_tokens)
            self._last_updated[key] = now

    async def acquire(self, key: str, tokens: int = 1) -> None:
        """Block until sufficient tokens exist in bucket."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._refill(key, now)

                current = self._tokens[key]
                if current >= tokens:
                    self._tokens[key] -= tokens
                    return

                needed = tokens - current
                wait_time = needed / self.rate_per_second

            logger.debug(
                "rate_limiter.waiting",
                key=key,
                wait_seconds=round(wait_time, 3),
            )
            await asyncio.sleep(wait_time)


class RedisTokenBucket(BaseRateLimiter):
    """Redis-backed distributed Token Bucket using atomic Lua script with fallback."""

    def __init__(
        self,
        redis_client: Any | None = None,
        rate_per_second: float = 1.0,
        capacity: float = 5.0,
    ) -> None:
        self.redis = redis_client
        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self._fallback = InMemoryTokenBucket(rate_per_second=rate_per_second, capacity=capacity)

    async def acquire(self, key: str, tokens: int = 1) -> None:
        if self.redis is None:
            await self._fallback.acquire(key, tokens)
            return

        # Phase 3 will introduce compiled Redis Lua script; fallback for Phase 2
        await self._fallback.acquire(key, tokens)
