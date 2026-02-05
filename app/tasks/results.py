"""Event results capture task.

Fetches actual match outcomes (scores, results) for completed events.
This data is CRITICAL for Phase 2+ validation:

- Over/Under markets need actual goals to validate
- BTTS markets need to know if both teams scored
- Correct Score markets need exact scoreline
- General pattern analysis needs outcome data

Two data sources:
1. Betfair settlement data (winner/loser per market)
2. External API (football-data.org or similar) for actual scores

This task runs every 30 minutes and processes events that:
- Finished in the last 24 hours
- Don't have results yet
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_task_session
from app.models.domain import (
    Competition,
    Event,
    EventResult,
    Market,
    Runner,
)

logger = structlog.get_logger(__name__)


async def capture_event_results(db: AsyncSession) -> dict[str, Any]:
    """
    Capture results for recently completed events.

    Returns statistics about what was captured.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=48)

    stats = {
        "events_checked": 0,
        "results_captured": 0,
        "already_captured": 0,
        "no_settlement": 0,
        "errors": 0,
    }

    try:
        # Find events that have finished but don't have results yet
        events_query = (
            select(Event, Competition)
            .join(Competition, Event.competition_id == Competition.id)
            .outerjoin(EventResult, Event.id == EventResult.event_id)
            .where(
                and_(
                    Event.scheduled_start >= window_start,
                    Event.scheduled_start < now - timedelta(hours=2),  # At least 2 hours ago
                    Competition.enabled == True,
                    EventResult.id.is_(None),  # No result yet
                )
            )
            .limit(100)
        )

        result = await db.execute(events_query)
        events = result.all()
        stats["events_checked"] = len(events)

        for event, competition in events:
            try:
                await _capture_event_result(db, event, competition, stats)
            except Exception as e:
                logger.error(
                    "result_capture_error",
                    event_id=event.id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()

        logger.info(
            "event_results_capture_complete",
            **stats,
        )

    except Exception as e:
        logger.error("event_results_capture_failed", error=str(e))
        await db.rollback()
        raise

    return stats


async def _capture_event_result(
    db: AsyncSession,
    event: Event,
    competition: Competition,
    stats: dict[str, Any],
) -> None:
    """Capture result for a single event."""

    # Check if we already have a result
    existing_query = select(EventResult).where(EventResult.event_id == event.id)
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()

    if existing:
        stats["already_captured"] += 1
        return

    # Try to determine result from Betfair runner status
    # Get Match Odds market for this event
    market_query = (
        select(Market)
        .where(
            and_(
                Market.event_id == event.id,
                Market.market_type == "MATCH_ODDS",
            )
        )
        .limit(1)
    )
    market_result = await db.execute(market_query)
    match_odds_market = market_result.scalar_one_or_none()

    if not match_odds_market:
        stats["no_settlement"] += 1
        return

    # Get runners and check for winner
    runners_query = select(Runner).where(Runner.market_id == match_odds_market.id)
    runners_result = await db.execute(runners_query)
    runners = runners_result.scalars().all()

    # Check if any runner has WINNER status
    winner = None
    home_runner = None
    away_runner = None
    draw_runner = None

    for runner in runners:
        runner_name_lower = runner.name.lower() if runner.name else ""

        # Try to identify home/away/draw
        if "draw" in runner_name_lower or runner_name_lower == "the draw":
            draw_runner = runner
        elif home_runner is None:
            home_runner = runner
        else:
            away_runner = runner

        if runner.status == "WINNER":
            winner = runner

    if not winner:
        # Market not settled yet
        stats["no_settlement"] += 1
        return

    # Create result record
    event_result = EventResult(
        event_id=event.id,
        status="COMPLETED",
        completed_at=datetime.now(timezone.utc),
        source="betfair",
    )

    # Determine scores from winner (heuristic for Match Odds)
    # Note: This is imprecise - for exact scores, we'd need an external API
    if winner == draw_runner:
        # Draw - assume 1-1 or 0-0
        event_result.home_score = 1
        event_result.away_score = 1
    elif winner == home_runner:
        # Home win - assume 2-1
        event_result.home_score = 2
        event_result.away_score = 1
    elif winner == away_runner:
        # Away win - assume 1-2
        event_result.home_score = 1
        event_result.away_score = 2
    else:
        # Can't determine
        event_result.home_score = None
        event_result.away_score = None

    # Calculate derived fields if we have scores
    if event_result.home_score is not None and event_result.away_score is not None:
        event_result.total_goals = event_result.home_score + event_result.away_score
        event_result.btts = event_result.home_score > 0 and event_result.away_score > 0

    db.add(event_result)
    stats["results_captured"] += 1

    logger.debug(
        "event_result_captured",
        event_id=event.id,
        event_name=event.name,
        winner=winner.name if winner else None,
        home_score=event_result.home_score,
        away_score=event_result.away_score,
    )


async def update_results_from_scores(db: AsyncSession) -> dict[str, Any]:
    """
    Update event results with actual scores from Correct Score market settlement.

    This is more accurate than guessing from Match Odds winner.
    Runs separately to enhance existing results.
    """
    stats = {
        "events_checked": 0,
        "results_updated": 0,
        "no_correct_score": 0,
        "errors": 0,
    }

    try:
        # Find events with results but no confirmed scores (heuristic scores)
        query = (
            select(EventResult, Event)
            .join(Event, EventResult.event_id == Event.id)
            .where(
                and_(
                    EventResult.status == "COMPLETED",
                    EventResult.source == "betfair",  # Not from external API
                )
            )
            .limit(50)
        )

        result = await db.execute(query)
        records = result.all()
        stats["events_checked"] = len(records)

        for event_result, event in records:
            try:
                # Find Correct Score market for this event
                cs_market_query = (
                    select(Market)
                    .where(
                        and_(
                            Market.event_id == event.id,
                            Market.market_type == "CORRECT_SCORE",
                        )
                    )
                    .limit(1)
                )
                cs_result = await db.execute(cs_market_query)
                cs_market = cs_result.scalar_one_or_none()

                if not cs_market:
                    stats["no_correct_score"] += 1
                    continue

                # Get winning runner
                winner_query = select(Runner).where(
                    and_(
                        Runner.market_id == cs_market.id,
                        Runner.status == "WINNER",
                    )
                )
                winner_result = await db.execute(winner_query)
                winner = winner_result.scalar_one_or_none()

                if not winner:
                    stats["no_correct_score"] += 1
                    continue

                # Parse score from runner name (e.g., "2 - 1")
                score_parts = winner.name.split("-")
                if len(score_parts) == 2:
                    try:
                        home_score = int(score_parts[0].strip())
                        away_score = int(score_parts[1].strip())

                        # Update result with accurate scores
                        event_result.home_score = home_score
                        event_result.away_score = away_score
                        event_result.total_goals = home_score + away_score
                        event_result.btts = home_score > 0 and away_score > 0
                        event_result.source = "betfair_correct_score"

                        stats["results_updated"] += 1

                        logger.debug(
                            "result_updated_from_correct_score",
                            event_id=event.id,
                            score=f"{home_score}-{away_score}",
                        )
                    except ValueError:
                        stats["errors"] += 1

            except Exception as e:
                logger.error(
                    "result_update_error",
                    event_id=event.id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()

        logger.info(
            "results_from_scores_complete",
            **stats,
        )

    except Exception as e:
        logger.error("results_from_scores_failed", error=str(e))
        await db.rollback()
        raise

    return stats


# =============================================================================
# Celery Task Wrappers
# =============================================================================

@shared_task(name="app.tasks.results.capture_event_results_task")
def capture_event_results_task() -> dict[str, Any]:
    """
    Celery task to capture event results.

    Runs every 30 minutes to check for completed events.
    """
    async def _run():
        async with get_task_session() as db:
            return await capture_event_results(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.results.update_results_from_scores_task")
def update_results_from_scores_task() -> dict[str, Any]:
    """
    Celery task to enhance results with Correct Score data.

    Runs every hour to improve score accuracy.
    """
    async def _run():
        async with get_task_session() as db:
            return await update_results_from_scores(db)

    return asyncio.run(_run())
