"""Market closure capture task.

Captures final scores and closing odds before markets go in-play.
This data is CRITICAL for Phase 1 validation.

Runs every 2 minutes and processes markets where:
- Event starts within the next 15 minutes
- Market is still OPEN (not yet in-play)
- No closing data has been captured yet

Philosophy:
- Closing odds are captured 5-10 minutes before event start
- This gives us the "fair price" benchmark for backtesting
- Final scores show what the system would have flagged as exploitable
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import and_, select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import get_task_session
from app.models.domain import (
    Event,
    ExploitabilityScore,
    Market,
    MarketClosingData,
    MarketSnapshot,
    Runner,
)

logger = structlog.get_logger(__name__)


async def capture_closing_data(db: AsyncSession) -> dict[str, Any]:
    """
    Capture final scores and closing odds for markets about to go in-play.

    Returns statistics about what was captured.
    """
    now = datetime.now(timezone.utc)
    window_start = now
    window_end = now + timedelta(minutes=15)

    stats = {
        "markets_checked": 0,
        "closing_odds_captured": 0,
        "final_scores_captured": 0,
        "already_captured": 0,
        "errors": 0,
    }

    try:
        # Find markets where event starts within 15 minutes and still OPEN
        markets_query = (
            select(Market, Event)
            .join(Event, Market.event_id == Event.id)
            .where(
                and_(
                    Event.scheduled_start >= window_start,
                    Event.scheduled_start <= window_end,
                    Market.status == "OPEN",
                    Market.in_play == False,
                )
            )
        )

        result = await db.execute(markets_query)
        markets = result.all()
        stats["markets_checked"] = len(markets)

        for market, event in markets:
            try:
                await _capture_market_closing(db, market, event, now, stats)
            except Exception as e:
                logger.error(
                    "closing_capture_error",
                    market_id=market.id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()

        logger.info(
            "closing_capture_complete",
            **stats,
        )

    except Exception as e:
        logger.error("closing_capture_failed", error=str(e))
        await db.rollback()
        raise

    return stats


async def _capture_market_closing(
    db: AsyncSession,
    market: Market,
    event: Event,
    now: datetime,
    stats: dict[str, Any],
) -> None:
    """Capture closing data for a single market."""

    # Check if we already have closing data
    existing_query = select(MarketClosingData).where(
        MarketClosingData.market_id == market.id
    )
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()

    # Calculate minutes to start
    minutes_to_start = int((event.scheduled_start - now).total_seconds() / 60)

    if existing:
        # Already captured - check if we need to update
        if existing.closing_odds and existing.final_score:
            stats["already_captured"] += 1
            return

        # Update existing record with new data if closer to start
        if existing.minutes_to_start and minutes_to_start >= existing.minutes_to_start:
            # We have fresher data already
            stats["already_captured"] += 1
            return

        closing_data = existing
    else:
        # Create new record
        closing_data = MarketClosingData(market_id=market.id)
        db.add(closing_data)

    # Capture closing odds from latest snapshot
    latest_snapshot_query = (
        select(MarketSnapshot)
        .where(MarketSnapshot.market_id == market.id)
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(1)
    )
    snapshot_result = await db.execute(latest_snapshot_query)
    latest_snapshot = snapshot_result.scalar_one_or_none()

    if latest_snapshot and latest_snapshot.ladder_data:
        # Get runner names for context
        runners_query = select(Runner).where(Runner.market_id == market.id)
        runners_result = await db.execute(runners_query)
        runners = {r.betfair_id: r.name for r in runners_result.scalars().all()}

        # Build closing odds structure
        closing_odds = {
            "captured_at": latest_snapshot.captured_at.isoformat(),
            "total_matched": float(latest_snapshot.total_matched or 0),
            "runners": [],
        }

        for runner_data in latest_snapshot.ladder_data.get("runners", []):
            runner_id = runner_data.get("runner_id")
            back_prices = runner_data.get("back", [])
            lay_prices = runner_data.get("lay", [])

            closing_odds["runners"].append({
                "runner_id": runner_id,
                "name": runners.get(runner_id, f"Runner {runner_id}"),
                "back_price": back_prices[0]["price"] if back_prices else None,
                "lay_price": lay_prices[0]["price"] if lay_prices else None,
                "last_traded": runner_data.get("last_traded"),
                "total_matched": runner_data.get("total_matched", 0),
            })

        closing_data.closing_snapshot_id = latest_snapshot.id
        closing_data.closing_odds = closing_odds
        closing_data.odds_captured_at = latest_snapshot.captured_at
        closing_data.minutes_to_start = minutes_to_start
        stats["closing_odds_captured"] += 1

        logger.debug(
            "closing_odds_captured",
            market_id=market.id,
            minutes_to_start=minutes_to_start,
            runners=len(closing_odds["runners"]),
        )

    # Capture final score
    latest_score_query = (
        select(ExploitabilityScore)
        .where(ExploitabilityScore.market_id == market.id)
        .order_by(ExploitabilityScore.scored_at.desc())
        .limit(1)
    )
    score_result = await db.execute(latest_score_query)
    latest_score = score_result.scalar_one_or_none()

    if latest_score:
        closing_data.final_score_id = latest_score.id
        closing_data.final_score = latest_score.total_score
        closing_data.score_captured_at = latest_score.scored_at
        stats["final_scores_captured"] += 1

        logger.debug(
            "final_score_captured",
            market_id=market.id,
            score=float(latest_score.total_score),
        )


async def capture_results(db: AsyncSession) -> dict[str, Any]:
    """
    Capture settlement results for markets that have closed.

    This runs separately (less frequently) to fetch final results
    after events have finished.

    Returns statistics about what was captured.
    """
    stats = {
        "markets_checked": 0,
        "results_captured": 0,
        "not_settled": 0,
        "errors": 0,
    }

    try:
        # Find markets with closing data but no settlement
        unsettled_query = (
            select(MarketClosingData, Market)
            .join(Market, MarketClosingData.market_id == Market.id)
            .where(
                and_(
                    MarketClosingData.settled_at.is_(None),
                    MarketClosingData.closing_odds.isnot(None),
                )
            )
            .limit(100)  # Process in batches
        )

        result = await db.execute(unsettled_query)
        records = result.all()
        stats["markets_checked"] = len(records)

        for closing_data, market in records:
            try:
                # Check if market is now settled by looking at runner status
                runners_query = select(Runner).where(Runner.market_id == market.id)
                runners_result = await db.execute(runners_query)
                runners = runners_result.scalars().all()

                # Check if any runner has WINNER/LOSER status
                winner = None
                runner_results = []

                for runner in runners:
                    if runner.status == "WINNER":
                        winner = runner
                    runner_results.append({
                        "runner_id": runner.betfair_id,
                        "name": runner.name,
                        "status": runner.status,
                    })

                if winner:
                    closing_data.result = {
                        "winner_runner_id": winner.betfair_id,
                        "winner_name": winner.name,
                        "runners": runner_results,
                    }
                    closing_data.settled_at = datetime.now(timezone.utc)
                    stats["results_captured"] += 1

                    logger.debug(
                        "result_captured",
                        market_id=market.id,
                        winner=winner.name,
                    )
                else:
                    stats["not_settled"] += 1

            except Exception as e:
                logger.error(
                    "result_capture_error",
                    market_id=market.id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()

        logger.info(
            "results_capture_complete",
            **stats,
        )

    except Exception as e:
        logger.error("results_capture_failed", error=str(e))
        await db.rollback()
        raise

    return stats


# =============================================================================
# Celery Task Wrappers
# =============================================================================

@shared_task(name="app.tasks.market_closure.capture_closing_data_task")
def capture_closing_data_task() -> dict[str, Any]:
    """
    Celery task to capture closing odds and final scores.

    Runs every 2 minutes to catch markets about to go in-play.
    """
    async def _run():
        async with get_task_session() as db:
            return await capture_closing_data(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.market_closure.capture_results_task")
def capture_results_task() -> dict[str, Any]:
    """
    Celery task to capture settlement results.

    Runs every 15 minutes to check for settled markets.
    """
    async def _run():
        async with get_task_session() as db:
            return await capture_results(db)

    return asyncio.run(_run())
