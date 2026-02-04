"""Rate limiter for Betfair API requests.

Implements a token bucket algorithm using Redis for distributed rate limiting.
Default: 5 requests/second with burst capacity of 10.
"""

import asyncio
import time
from typing import Any

import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class BetfairRateLimiter:
    """
    Token bucket rate limiter using Redis.

    Ensures we don't exceed Betfair's API rate limits.
    Default: 5 requests/second with burst of 10.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        rate: float = 5.0,
        burst: int = 10,
        key_prefix: str = "ratelimit:betfair",
    ):
        """
        Initialize the rate limiter.

        Args:
            redis_client: Redis client for distributed state
            rate: Requests per second allowed
            burst: Maximum burst size
            key_prefix: Redis key prefix
        """
        self.redis = redis_client
        self.rate = rate
        self.burst = burst
        self.key_prefix = key_prefix
        self.refill_interval = 1.0 / rate  # Time to add one token

    def _get_key(self, endpoint: str) -> str:
        """Get Redis key for endpoint."""
        return f"{self.key_prefix}:{endpoint}"

    async def acquire(self, endpoint: str = "default") -> bool:
        """
        Try to acquire a token for the given endpoint.

        Args:
            endpoint: API endpoint being called

        Returns:
            True if token acquired, False if rate limited
        """
        key = self._get_key(endpoint)
        now = time.time()

        # Lua script for atomic token bucket operation
        # Returns: (tokens_remaining, wait_time_if_needed)
        lua_script = """
        local key = KEYS[1]
        local rate = tonumber(ARGV[1])
        local burst = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local refill_interval = tonumber(ARGV[4])

        -- Get current state
        local state = redis.call('HMGET', key, 'tokens', 'last_update')
        local tokens = tonumber(state[1]) or burst
        local last_update = tonumber(state[2]) or now

        -- Calculate tokens to add based on time passed
        local elapsed = now - last_update
        local tokens_to_add = elapsed * rate
        tokens = math.min(burst, tokens + tokens_to_add)

        -- Try to consume a token
        if tokens >= 1 then
            tokens = tokens - 1
            redis.call('HMSET', key, 'tokens', tokens, 'last_update', now)
            redis.call('EXPIRE', key, 60)  -- Clean up after 60s of inactivity
            return {1, 0}  -- Success, no wait needed
        else
            -- Calculate wait time until next token
            local wait_time = refill_interval - (elapsed % refill_interval)
            return {0, wait_time}  -- Failed, return wait time
        end
        """

        try:
            result = await self.redis.eval(
                lua_script,
                1,
                key,
                str(self.rate),
                str(self.burst),
                str(now),
                str(self.refill_interval),
            )
            success = result[0] == 1
            if not success:
                wait_time = result[1]
                logger.debug(
                    "rate_limited",
                    endpoint=endpoint,
                    wait_time=wait_time,
                )
            return success
        except Exception as e:
            logger.error("rate_limiter_error", error=str(e), endpoint=endpoint)
            # Fail open - allow request if Redis fails
            return True

    async def wait_if_needed(self, endpoint: str = "default") -> None:
        """
        Block until a token is available.

        Args:
            endpoint: API endpoint being called
        """
        max_wait = 10.0  # Maximum wait time in seconds
        total_wait = 0.0

        while not await self.acquire(endpoint):
            wait_time = min(0.1, max_wait - total_wait)
            if total_wait >= max_wait:
                logger.warning(
                    "rate_limiter_max_wait_exceeded",
                    endpoint=endpoint,
                    total_wait=total_wait,
                )
                break
            await asyncio.sleep(wait_time)
            total_wait += wait_time

    async def get_stats(self, endpoint: str = "default") -> dict[str, Any]:
        """Get current rate limiter stats for an endpoint."""
        key = self._get_key(endpoint)
        try:
            state = await self.redis.hgetall(key)
            return {
                "endpoint": endpoint,
                "tokens": float(state.get(b"tokens", self.burst)),
                "last_update": float(state.get(b"last_update", 0)),
                "rate": self.rate,
                "burst": self.burst,
            }
        except Exception as e:
            logger.error("get_stats_error", error=str(e))
            return {"endpoint": endpoint, "error": str(e)}
