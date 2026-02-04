"""FastAPI dependencies for RidgeRadar."""

from collections.abc import AsyncGenerator

import redis.asyncio as redis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.base import async_session_factory
from app.services.betfair_client import BetfairClient


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """Get Redis client dependency."""
    settings = get_settings()
    client = redis.from_url(settings.redis_url)
    try:
        yield client
    finally:
        await client.close()


async def get_betfair_client(
    redis_client: redis.Redis = Depends(get_redis),
) -> AsyncGenerator[BetfairClient, None]:
    """Get Betfair client dependency."""
    async with BetfairClient(redis_client=redis_client) as client:
        yield client
