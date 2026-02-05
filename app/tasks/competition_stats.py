"""Competition statistics aggregation task.

This task computes aggregate statistics for each competition based on
the scores of its markets. This allows us to LEARN which competitions
consistently produce high-scoring (exploitable) markets.

Philosophy:
- We don't pre-judge competitions by name
- We let the data tell us which competitions are valuable
- Competitions with consistently low scores can be deprioritised
- Competitions with consistently high scores get more attention
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import structlog
import yaml
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.base import async_session_factory, get_task_session
from app.models.domain import (
    Competition,
    CompetitionStats,
    Event,
    ExploitabilityScore,
    JobRun,
    Market,
)
from app.tasks import celery_app

logger = structlog.get_logger(__name__)


def _load_config() -> dict[str, Any]:
    """Load configuration from defaults.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "defaults.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


@celery_app.task(bind=True, name="aggregate_competition_stats", queue="fixtures")
def aggregate_competition_stats_task(self, target_date: str | None = None):
    """
    Celery task wrapper for competition stats aggregation.

    Args:
        target_date: Date to aggregate stats for (YYYY-MM-DD format).
                     Defaults to today.
    """
    import asyncio

    if target_date:
        dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        dt = datetime.now(timezone.utc).date()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(aggregate_competition_stats(dt, self))
    finally:
        loop.close()


async def aggregate_competition_stats(
    target_date: date | None = None,
    task: Any = None,
) -> dict[str, Any]:
    """
    Aggregate statistics for all competitions based on market scores.

    For each competition:
    1. Find all markets that were scored today
    2. Calculate aggregate statistics (avg, max, min, std dev)
    3. Count markets above various thresholds
    4. Calculate rolling 30-day average
    5. Store in competition_stats table

    Args:
        target_date: Date to aggregate stats for. Defaults to today.
        task: Celery task instance for logging.

    Returns:
        Dict with aggregation statistics.
    """
    started_at = datetime.now(timezone.utc)

    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    config = _load_config()
    tracking_config = config.get("competition_tracking", {})

    stats = {
        "competitions_processed": 0,
        "competitions_with_scores": 0,
        "total_markets_scored": 0,
        "high_value_competitions": 0,
        "low_value_competitions": 0,
    }

    async with get_task_session() as session:
        # Create job run record
        job_run = JobRun(
            job_name="aggregate_competition_stats",
            started_at=started_at,
            status="running",
            job_metadata={"target_date": str(target_date)},
        )
        session.add(job_run)
        await session.commit()

        job_status = "success"
        error_message = None

        try:
            # Get all enabled competitions
            result = await session.execute(
                select(Competition).where(Competition.enabled == True)
            )
            competitions = result.scalars().all()

            for competition in competitions:
                stats["competitions_processed"] += 1

                # Get scores for this competition's markets from today
                # Join through Event -> Market -> ExploitabilityScore
                score_query = (
                    select(ExploitabilityScore)
                    .join(Market, ExploitabilityScore.market_id == Market.id)
                    .join(Event, Market.event_id == Event.id)
                    .where(
                        Event.competition_id == competition.id,
                        func.date(ExploitabilityScore.scored_at) == target_date,
                    )
                )
                score_result = await session.execute(score_query)
                scores = score_result.scalars().all()

                if not scores:
                    continue

                stats["competitions_with_scores"] += 1
                stats["total_markets_scored"] += len(scores)

                # Calculate statistics
                score_values = [float(s.total_score) for s in scores]
                volume_values = [
                    float(s.volume_penalty) if s.volume_penalty else 0 for s in scores
                ]

                avg_score = mean(score_values)
                max_score = max(score_values)
                min_score = min(score_values)
                score_std = stdev(score_values) if len(score_values) > 1 else 0

                # Count markets above thresholds
                above_40 = sum(1 for s in score_values if s >= 40)
                above_55 = sum(1 for s in score_values if s >= 55)
                above_70 = sum(1 for s in score_values if s >= 70)

                # Calculate rolling 30-day average
                thirty_days_ago = target_date - timedelta(days=30)
                rolling_query = (
                    select(func.avg(CompetitionStats.avg_score))
                    .where(
                        CompetitionStats.competition_id == competition.id,
                        CompetitionStats.stats_date >= thirty_days_ago,
                        CompetitionStats.stats_date < target_date,
                    )
                )
                rolling_result = await session.execute(rolling_query)
                rolling_avg = rolling_result.scalar()

                # Include today's average in rolling calculation
                if rolling_avg is not None:
                    rolling_30d = (float(rolling_avg) + avg_score) / 2
                else:
                    rolling_30d = avg_score

                # Track high/low value competitions
                high_threshold = tracking_config.get("high_value_threshold", 60)
                low_threshold = tracking_config.get("low_value_threshold", 35)

                if avg_score >= high_threshold:
                    stats["high_value_competitions"] += 1
                elif avg_score < low_threshold:
                    stats["low_value_competitions"] += 1

                # Upsert statistics
                stmt = insert(CompetitionStats).values(
                    competition_id=competition.id,
                    stats_date=target_date,
                    markets_scored=len(scores),
                    avg_score=Decimal(str(round(avg_score, 2))),
                    max_score=Decimal(str(round(max_score, 2))),
                    min_score=Decimal(str(round(min_score, 2))),
                    score_std_dev=Decimal(str(round(score_std, 2))),
                    markets_above_40=above_40,
                    markets_above_55=above_55,
                    markets_above_70=above_70,
                    rolling_30d_avg_score=Decimal(str(round(rolling_30d, 2))),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["competition_id", "stats_date"],
                    set_={
                        "markets_scored": len(scores),
                        "avg_score": Decimal(str(round(avg_score, 2))),
                        "max_score": Decimal(str(round(max_score, 2))),
                        "min_score": Decimal(str(round(min_score, 2))),
                        "score_std_dev": Decimal(str(round(score_std, 2))),
                        "markets_above_40": above_40,
                        "markets_above_55": above_55,
                        "markets_above_70": above_70,
                        "rolling_30d_avg_score": Decimal(str(round(rolling_30d, 2))),
                        "updated_at": func.now(),
                    },
                )
                await session.execute(stmt)

                logger.debug(
                    "competition_stats_calculated",
                    competition=competition.name,
                    markets=len(scores),
                    avg_score=round(avg_score, 2),
                    rolling_30d=round(rolling_30d, 2),
                )

            await session.commit()

            logger.info(
                "competition_stats_complete",
                date=str(target_date),
                **stats,
            )

        except Exception as e:
            job_status = "failed"
            error_message = str(e)
            logger.exception(
                "competition_stats_failed",
                error=str(e),
            )
            raise

        finally:
            # Update job run record
            job_run.completed_at = datetime.now(timezone.utc)
            job_run.status = job_status
            job_run.error_message = error_message
            job_run.records_processed = stats["competitions_with_scores"]
            job_run.job_metadata = {
                "target_date": str(target_date),
                **stats,
            }
            await session.commit()

    return stats


async def get_competition_rankings(
    min_markets: int = 10,
    days: int = 30,
) -> list[dict[str, Any]]:
    """
    Get competition rankings based on rolling average scores.

    Returns competitions sorted by their average score over the past N days,
    allowing us to identify which competitions consistently produce
    high-scoring (exploitable) markets.

    Args:
        min_markets: Minimum markets scored to be included in rankings.
        days: Number of days for the rolling window.

    Returns:
        List of competition rankings with statistics.
    """
    async with async_session_factory() as session:
        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days)

        # Aggregate stats for each competition over the period
        query = (
            select(
                Competition.id,
                Competition.name,
                Competition.country_code,
                func.sum(CompetitionStats.markets_scored).label("total_markets"),
                func.avg(CompetitionStats.avg_score).label("avg_score"),
                func.max(CompetitionStats.max_score).label("max_score"),
                func.sum(CompetitionStats.markets_above_55).label("markets_above_55"),
                func.sum(CompetitionStats.markets_above_70).label("markets_above_70"),
            )
            .join(CompetitionStats, Competition.id == CompetitionStats.competition_id)
            .where(
                Competition.enabled == True,
                CompetitionStats.stats_date >= cutoff_date,
            )
            .group_by(Competition.id, Competition.name, Competition.country_code)
            .having(func.sum(CompetitionStats.markets_scored) >= min_markets)
            .order_by(func.avg(CompetitionStats.avg_score).desc())
        )

        result = await session.execute(query)
        rows = result.all()

        rankings = []
        for row in rows:
            rankings.append({
                "competition_id": row.id,
                "name": row.name,
                "country_code": row.country_code,
                "total_markets": row.total_markets,
                "avg_score": float(row.avg_score) if row.avg_score else 0,
                "max_score": float(row.max_score) if row.max_score else 0,
                "markets_above_55": row.markets_above_55 or 0,
                "markets_above_70": row.markets_above_70 or 0,
            })

        return rankings
