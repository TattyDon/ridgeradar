"""Health check endpoints."""

from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_betfair_client, get_db, get_redis
from app.config import get_settings
from app.services.betfair_client import BetfairClient

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: datetime


class ReadyCheck(BaseModel):
    """Individual readiness check."""

    status: str
    message: str | None = None


class ReadyResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    checks: dict[str, ReadyCheck]


@router.get("/health", response_model=HealthResponse)
async def health():
    """
    Basic health check.

    Returns healthy if the service is running.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready(
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Readiness check for all dependencies.

    Checks:
    - Database connectivity
    - Redis connectivity
    - Betfair credentials configured
    """
    checks = {}
    all_ready = True

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = ReadyCheck(status="ok")
    except Exception as e:
        checks["db"] = ReadyCheck(status="error", message=str(e))
        all_ready = False

    # Check Redis
    try:
        await redis_client.ping()
        checks["redis"] = ReadyCheck(status="ok")
    except Exception as e:
        checks["redis"] = ReadyCheck(status="error", message=str(e))
        all_ready = False

    # Check Betfair configuration
    settings = get_settings()
    if settings.betfair_configured:
        checks["betfair"] = ReadyCheck(status="ok", message="Credentials configured")
    else:
        checks["betfair"] = ReadyCheck(
            status="warning", message="Credentials not configured"
        )
        # Don't mark as not ready, just warn

    return ReadyResponse(ready=all_ready, checks=checks)


@router.get("/health/betfair")
async def betfair_health(
    betfair: BetfairClient = Depends(get_betfair_client),
):
    """
    Check Betfair API connectivity.

    Attempts to authenticate and fetch event types.
    """
    try:
        is_healthy = await betfair.health_check()
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "timestamp": datetime.now(timezone.utc),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc),
        }
