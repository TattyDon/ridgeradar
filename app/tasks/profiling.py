"""Daily profiling task.

Aggregates snapshot data into daily profiles by time bucket.
"""

from datetime import date, datetime, timezone

import structlog

from app.models.base import get_task_session
from app.models.domain import JobRun
from app.services.profiling import ProfilingService
from app.tasks import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, soft_time_limit=540, time_limit=600)
def compute_daily_profiles(self, profile_date: str | None = None):
    """
    Scheduled: Hourly at :05
    Timeout: 10 minutes

    For each market with snapshots today:
    1. Group snapshots by time bucket:
       - 72h+, 24-72h, 6-24h, 2-6h, <2h
    2. Calculate metrics per bucket:
       - avg_spread_ticks
       - spread_volatility
       - avg_depth_best
       - depth_5_ticks
       - total_matched_volume
       - update_rate_per_min
       - price_volatility
       - mean_price
       - snapshot_count
    3. Upsert to market_profiles_daily
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_compute_profiles_async(self, profile_date))
    finally:
        loop.close()


async def _compute_profiles_async(task, profile_date_str: str | None = None):
    """Async implementation of profile computation."""
    started_at = datetime.now(timezone.utc)
    job_status = "running"
    error_message = None
    stats = {}

    # Parse date or use today
    if profile_date_str:
        target_date = date.fromisoformat(profile_date_str)
    else:
        target_date = datetime.now(timezone.utc).date()

    async with get_task_session() as session:
        # Create job run record
        job_run = JobRun(
            job_name="compute_daily_profiles",
            started_at=started_at,
            status="running",
            job_metadata={"profile_date": str(target_date)},
        )
        session.add(job_run)
        await session.commit()

        try:
            # Run profiling
            profiling_service = ProfilingService(session)
            stats = await profiling_service.compute_profiles_for_date(target_date)

            job_status = "success"
            logger.info(
                "profiling_task_complete",
                date=str(target_date),
                markets=stats.get("markets_processed", 0),
                profiles=stats.get("profiles_created", 0),
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
            )

        except Exception as e:
            job_status = "failed"
            error_message = str(e)
            logger.error(
                "profiling_task_failed",
                error=str(e),
                task_id=task.request.id,
            )

        finally:
            # Update job run record
            job_run.completed_at = datetime.now(timezone.utc)
            job_run.status = job_status
            job_run.error_message = error_message
            job_run.records_processed = stats.get("profiles_created", 0)
            job_run.job_metadata = {
                "profile_date": str(target_date),
                **stats,
            }
            await session.commit()

    return stats
