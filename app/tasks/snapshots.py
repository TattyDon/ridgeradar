"""Snapshot capture task.

Captures point-in-time market state (ladder data) for active markets.
Excludes markets from disabled competitions and in-play markets.
"""

from datetime import datetime, timezone

import redis.asyncio as redis
import structlog

from app.config import get_settings
from app.models.base import get_task_session
from app.models.domain import JobRun
from app.services.betfair_client import BetfairClient
from app.services.ingestion import SnapshotCaptureService
from app.tasks import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, soft_time_limit=45, time_limit=60)
def capture_snapshots(self, market_ids: list[int] | None = None):
    """
    Scheduled: Every 60 seconds
    Timeout: 45 seconds

    Process:
    1. Get active markets (status='OPEN', not in_play, competition enabled)
    2. Batch into groups of 40 (Betfair limit)
    3. For each batch:
       a. Call listMarketBook with:
          - priceProjection: EX_BEST_OFFERS, EX_TRADED
          - orderProjection: EXECUTABLE
       b. Extract per runner:
          - Back prices (top 3 levels)
          - Lay prices (top 3 levels)
          - Last traded price
          - Total matched
       c. Calculate:
          - Spread in ticks
          - Best depth (back + lay at best)
          - Overround
    4. Store as MarketSnapshot with JSONB ladder
    5. Log job run
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_capture_snapshots_async(self, market_ids))
    finally:
        loop.close()


async def _capture_snapshots_async(task, market_ids: list[int] | None = None):
    """Async implementation of snapshot capture."""
    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    job_status = "running"
    error_message = None
    stats = {}

    async with get_task_session() as session:
        # Create job run record
        job_run = JobRun(
            job_name="capture_snapshots",
            started_at=started_at,
            status="running",
        )
        session.add(job_run)
        await session.commit()

        try:
            # Create Redis client
            redis_client = redis.from_url(settings.redis_url)

            async with BetfairClient(redis_client=redis_client) as betfair:
                # Run snapshot capture
                snapshot_service = SnapshotCaptureService(
                    betfair_client=betfair,
                    session=session,
                    ladder_depth=1,  # Only best price to avoid TOO_MUCH_DATA
                    max_markets_per_batch=5,  # Very small batch to avoid TOO_MUCH_DATA
                )
                stats = await snapshot_service.capture_snapshots(market_ids)

            job_status = "success"
            logger.info(
                "snapshot_task_complete",
                snapshots=stats.get("snapshots_stored", 0),
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
            )

        except Exception as e:
            job_status = "failed"
            error_message = str(e)
            logger.error(
                "snapshot_task_failed",
                error=str(e),
                task_id=task.request.id,
            )

        finally:
            # Update job run record
            job_run.completed_at = datetime.now(timezone.utc)
            job_run.status = job_status
            job_run.error_message = error_message
            job_run.records_processed = stats.get("snapshots_stored", 0)
            job_run.job_metadata = stats
            await session.commit()

    return stats
