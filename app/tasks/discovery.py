"""Market discovery task.

Discovers competitions, events, and markets from Betfair.

Philosophy: Ingest broadly, filter by score.
- Hard exclusions only for things that waste API quota (friendlies, youth, etc.)
- Everything else gets ingested and the scoring engine filters automatically
"""

from datetime import datetime, timezone

import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.base import get_task_session
from app.models.domain import JobRun
from app.services.betfair_client import BetfairClient
from app.services.ingestion import MarketDiscoveryService
from app.tasks import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, max_retries=3, soft_time_limit=300, time_limit=360, queue="fixtures")
def discover_markets(self):
    """
    Scheduled: Every 15 minutes
    Timeout: 5 minutes

    Process:
    1. Load enabled sports from config
    2. Fetch competitions from Betfair
    3. Apply hard exclusions only (friendlies, youth, reserves, etc.)
    4. For enabled competitions:
       a. Fetch events (next 72 hours)
       b. Fetch market catalogues
    5. Upsert all entities to database
    6. Mark stale events as CLOSED
    7. Log job run with stats

    The scoring engine automatically penalizes efficient markets (EPL, UCL, etc.)
    via the volume penalty - no need for name-based tier filtering.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_discover_markets_async(self))
    finally:
        loop.close()


async def _discover_markets_async(task):
    """Async implementation of market discovery."""
    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    job_status = "running"
    error_message = None
    stats = {}

    async with get_task_session() as session:
        # Create job run record
        job_run = JobRun(
            job_name="discover_markets",
            started_at=started_at,
            status="running",
        )
        session.add(job_run)
        await session.commit()

        try:
            # Create Redis client for Betfair auth caching
            redis_client = redis.from_url(settings.redis_url)

            async with BetfairClient(redis_client=redis_client) as betfair:
                # Run discovery
                discovery = MarketDiscoveryService(
                    betfair_client=betfair,
                    session=session,
                )
                stats = await discovery.discover_all()

            job_status = "success"
            logger.info(
                "discovery_task_complete",
                stats=stats,
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
            )

        except Exception as e:
            job_status = "failed"
            error_message = str(e)
            logger.error(
                "discovery_task_failed",
                error=str(e),
                task_id=task.request.id,
            )

            # Retry on transient errors
            if task.request.retries < task.max_retries:
                raise task.retry(exc=e, countdown=60 * (task.request.retries + 1))

        finally:
            # Update job run record
            job_run.completed_at = datetime.now(timezone.utc)
            job_run.status = job_status
            job_run.error_message = error_message
            job_run.records_processed = (
                stats.get("competitions", 0)
                + stats.get("events", 0)
                + stats.get("markets", 0)
            )
            job_run.job_metadata = stats
            await session.commit()

    return stats
