"""Market scoring task.

Calculates exploitability scores for markets based on their profiles.

Philosophy: High volume markets score LOW (they are efficient = bad for us).
The scoring engine automatically penalizes efficient markets, so we don't
need name-based tier filtering anymore.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_task_session
from app.models.domain import (
    Competition,
    Event,
    ExploitabilityScore,
    JobRun,
    Market,
    MarketProfileDaily,
)
from app.services.profiling.metrics import get_odds_band
from app.services.scoring import ScoringEngine
from app.services.scoring.engine import MarketMetrics
from app.tasks import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, soft_time_limit=150, time_limit=180, queue="odds")
def score_markets(self):
    """
    Scheduled: Every 5 minutes
    Timeout: 3 minutes

    For each market with recent profile:
    1. Skip if competition is disabled (hard exclusions)
    2. Skip if insufficient snapshots
    3. Calculate score using ScoringEngine
    4. Store in exploitability_scores table
    5. Log high scores (>60) for monitoring
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_score_markets_async(self))
    finally:
        loop.close()


async def _score_markets_async(task):
    """Async implementation of market scoring."""
    started_at = datetime.now(timezone.utc)
    job_status = "running"
    error_message = None
    stats = {
        "markets_processed": 0,
        "scores_created": 0,
        "high_scores": 0,
        "skipped_excluded": 0,
        "skipped_insufficient_data": 0,
    }

    async with get_task_session() as session:
        # Create job run record
        job_run = JobRun(
            job_name="score_markets",
            started_at=started_at,
            status="running",
        )
        session.add(job_run)
        await session.commit()

        try:
            # Initialize scoring engine
            engine = ScoringEngine()

            # Get today's date
            today = datetime.now(timezone.utc).date()

            # Get markets with recent profiles from enabled competitions
            result = await session.execute(
                select(Market, MarketProfileDaily)
                .join(Event)
                .join(Competition)
                .join(
                    MarketProfileDaily,
                    Market.id == MarketProfileDaily.market_id,
                )
                .where(
                    Competition.enabled == True,
                    Market.status == "OPEN",
                    MarketProfileDaily.profile_date == today,
                )
            )

            rows = result.all()
            scored_markets = set()

            for market, profile in rows:
                stats["markets_processed"] += 1

                # Skip if already scored this run
                if market.id in scored_markets:
                    continue
                scored_markets.add(market.id)

                # Check data sufficiency
                if profile.snapshot_count < 5:
                    stats["skipped_insufficient_data"] += 1
                    continue

                # Build metrics for scoring
                metrics = MarketMetrics(
                    spread_ticks=float(profile.avg_spread_ticks or 0),
                    volatility=float(profile.price_volatility or 0),
                    update_rate=float(profile.update_rate_per_min or 0),
                    depth=float(profile.avg_depth_best or 0),
                    volume=float(profile.total_matched_volume or 0),
                    mean_price=float(profile.mean_price or 0),
                    snapshot_count=profile.snapshot_count or 0,
                )

                # Calculate score
                result = engine.calculate_score(metrics)

                # Determine odds band from mean price
                odds_band = get_odds_band(metrics.mean_price or 2.0)

                # Store score
                score = ExploitabilityScore(
                    market_id=market.id,
                    scored_at=datetime.now(timezone.utc),
                    time_bucket=profile.time_bucket,
                    odds_band=odds_band,
                    spread_score=Decimal(str(result.spread_score)),
                    volatility_score=Decimal(str(result.volatility_score)),
                    update_score=Decimal(str(result.update_score)),
                    depth_score=Decimal(str(result.depth_score)),
                    volume_penalty=Decimal(str(result.volume_penalty)),
                    total_score=Decimal(str(result.total_score)),
                )
                session.add(score)
                stats["scores_created"] += 1

                # Track high scores
                if result.total_score > 60:
                    stats["high_scores"] += 1
                    logger.info(
                        "high_score_market",
                        market_id=market.id,
                        market_name=market.name,
                        score=result.total_score,
                        time_bucket=profile.time_bucket,
                    )

            await session.commit()
            job_status = "success"

            logger.info(
                "scoring_task_complete",
                markets=stats["markets_processed"],
                scores=stats["scores_created"],
                high_scores=stats["high_scores"],
                duration_seconds=(datetime.now(timezone.utc) - started_at).total_seconds(),
            )

        except Exception as e:
            job_status = "failed"
            error_message = str(e)
            logger.error(
                "scoring_task_failed",
                error=str(e),
                task_id=task.request.id,
            )

        finally:
            # Update job run record
            job_run.completed_at = datetime.now(timezone.utc)
            job_run.status = job_status
            job_run.error_message = error_message
            job_run.records_processed = stats["scores_created"]
            job_run.job_metadata = stats
            await session.commit()

    return stats
