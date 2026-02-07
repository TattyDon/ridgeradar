"""Shadow Trading Task.

Phase 2: Paper trading simulation that records hypothetical trading decisions
based on the scoring system. NO REAL MONEY IS EVER AT RISK.

This module handles:
1. Checking if shadow trading should be active (threshold-based)
2. Making shadow decisions on high-scoring markets
3. Capturing closing prices for CLV calculation
4. Settling decisions and calculating theoretical P&L

SAFETY: This is PAPER TRADING only. Phase 3 (live trading) requires
explicit code changes and will NEVER auto-activate.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from celery import shared_task
from sqlalchemy import and_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.shadow_trading import (
    DecisionStrategy,
    ShadowTradingConfig,
    TradingPhase,
    get_shadow_config,
)
from app.models.base import get_task_session
from app.models.domain import (
    Competition,
    Event,
    ExploitabilityScore,
    Market,
    MarketClosingData,
    MarketSnapshot,
    Runner,
    ShadowDecision,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# Phase Status Check
# =============================================================================

async def get_current_phase(db: AsyncSession) -> tuple[TradingPhase, dict]:
    """
    Determine the current trading phase based on data thresholds.

    Returns:
        Tuple of (phase, details_dict)
    """
    config = get_shadow_config()

    # Check if shadow trading is disabled
    if not config.enabled:
        return TradingPhase.PHASE1_COLLECTING, {"reason": "Shadow trading disabled"}

    # Get current data counts
    query = text("""
        SELECT
            COUNT(*) AS total_closing_data,
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS total_with_results,
            COUNT(*) FILTER (WHERE final_score >= 30) AS high_score_markets,
            EXTRACT(DAY FROM (MAX(created_at) - MIN(created_at))) + 1 AS days_collecting
        FROM market_closing_data
    """)

    result = await db.execute(query)
    row = result.one()

    closing_data = row.total_closing_data or 0
    results = row.total_with_results or 0
    high_score = row.high_score_markets or 0
    days = int(row.days_collecting or 0)

    # Check thresholds
    ready, details = config.activation.check_ready(
        closing_data=closing_data,
        results=results,
        high_score=high_score,
        days=days
    )

    if ready and config.auto_activate_phase2:
        return TradingPhase.PHASE2_SHADOW, details

    return TradingPhase.PHASE1_COLLECTING, details


# =============================================================================
# Decision Making Logic
# =============================================================================

async def find_tradeable_markets(
    db: AsyncSession,
    config: ShadowTradingConfig
) -> list[tuple[Market, Event, ExploitabilityScore]]:
    """
    Find markets that meet entry criteria for shadow trading.

    Criteria:
    - Score >= min_score
    - Within time window (min_minutes to max_minutes before start)
    - Market status is OPEN
    - Not in-play
    - Sufficient liquidity
    - No existing shadow decision
    """
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=config.entry.min_minutes_to_start)
    window_end = now + timedelta(minutes=config.entry.max_minutes_to_start)

    # Find markets meeting criteria
    query = text("""
        WITH latest_scores AS (
            SELECT DISTINCT ON (market_id)
                id, market_id, total_score, scored_at
            FROM exploitability_scores
            ORDER BY market_id, scored_at DESC
        )
        SELECT
            m.id AS market_id,
            m.betfair_id AS market_betfair_id,
            m.name AS market_name,
            m.market_type,
            m.status AS market_status,
            m.in_play,
            m.total_matched,
            e.id AS event_id,
            e.name AS event_name,
            e.scheduled_start,
            c.id AS competition_id,
            c.name AS competition_name,
            ls.id AS score_id,
            ls.total_score
        FROM markets m
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        JOIN latest_scores ls ON m.id = ls.market_id
        LEFT JOIN shadow_decisions sd ON m.id = sd.market_id
        WHERE
            c.enabled = true
            AND m.status = :market_status
            AND (m.in_play = false OR m.in_play IS NULL)
            AND e.scheduled_start >= :window_start
            AND e.scheduled_start <= :window_end
            AND ls.total_score >= :min_score
            AND (m.total_matched IS NULL OR m.total_matched >= :min_liquidity)
            AND sd.id IS NULL  -- No existing decision
        ORDER BY ls.total_score DESC
        LIMIT 50
    """)

    result = await db.execute(query, {
        "market_status": config.entry.market_status,
        "window_start": window_start,
        "window_end": window_end,
        "min_score": float(config.entry.min_score),
        "min_liquidity": float(config.entry.min_total_matched),
    })

    return result.fetchall()


def select_runner_for_decision(
    runners: list[Runner],
    market_type: str,
    config: ShadowTradingConfig,
    latest_snapshot: Optional[MarketSnapshot]
) -> tuple[Optional[Runner], str, str]:
    """
    Select which runner to back/lay based on market type rules.

    Returns:
        Tuple of (runner, decision_type, reason)
    """
    rule = config.get_market_rule(market_type)

    if not rule.enabled or rule.strategy == DecisionStrategy.SKIP:
        return None, "", f"Market type {market_type} is not traded"

    # For pattern-based selection (O/U, BTTS)
    if rule.runner_name_pattern:
        pattern = re.compile(rule.runner_name_pattern, re.IGNORECASE)
        for runner in runners:
            if runner.name and pattern.search(runner.name):
                return runner, "BACK", f"Matched pattern '{rule.runner_name_pattern}'"
        return None, "", f"No runner matched pattern '{rule.runner_name_pattern}'"

    # For value-based selection (Match Odds, etc.)
    if rule.strategy == DecisionStrategy.BACK_BEST_VALUE:
        # In absence of more sophisticated logic, back the runner
        # with best odds (highest back price = underdog = more value if correct)
        # This is a simplified heuristic - could be enhanced with model
        if latest_snapshot and latest_snapshot.ladder_data:
            best_runner = None
            best_price = Decimal("0")

            runner_map = {r.betfair_id: r for r in runners}
            ladder_runners = latest_snapshot.ladder_data.get("runners", [])

            for lr in ladder_runners:
                runner_id = lr.get("runner_id")
                back_prices = lr.get("back", [])
                if back_prices and runner_id in runner_map:
                    price = Decimal(str(back_prices[0].get("price", 0)))
                    # Prefer mid-range odds (2.0 - 6.0) for balance of value/probability
                    if Decimal("2.0") <= price <= Decimal("6.0"):
                        if price > best_price:
                            best_price = price
                            best_runner = runner_map[runner_id]

            if best_runner:
                return best_runner, "BACK", f"Best value in 2.0-6.0 range at {best_price}"

        # Fallback: back the first non-draw runner
        for runner in runners:
            name_lower = (runner.name or "").lower()
            if "draw" not in name_lower and "the draw" not in name_lower:
                return runner, "BACK", "First non-draw runner (fallback)"

    if rule.strategy == DecisionStrategy.BACK_FAVORITE:
        # Find lowest priced runner
        if latest_snapshot and latest_snapshot.ladder_data:
            best_runner = None
            best_price = Decimal("1000")
            runner_map = {r.betfair_id: r for r in runners}

            for lr in latest_snapshot.ladder_data.get("runners", []):
                runner_id = lr.get("runner_id")
                back_prices = lr.get("back", [])
                if back_prices and runner_id in runner_map:
                    price = Decimal(str(back_prices[0].get("price", 0)))
                    if price < best_price and price > Decimal("1.01"):
                        best_price = price
                        best_runner = runner_map[runner_id]

            if best_runner:
                return best_runner, "BACK", f"Favorite at {best_price}"

    if rule.strategy == DecisionStrategy.LAY_FAVORITE:
        # Find lowest priced runner to lay
        if latest_snapshot and latest_snapshot.ladder_data:
            best_runner = None
            best_price = Decimal("1000")
            runner_map = {r.betfair_id: r for r in runners}

            for lr in latest_snapshot.ladder_data.get("runners", []):
                runner_id = lr.get("runner_id")
                lay_prices = lr.get("lay", [])
                if lay_prices and runner_id in runner_map:
                    price = Decimal(str(lay_prices[0].get("price", 0)))
                    if price < best_price and price > Decimal("1.01"):
                        best_price = price
                        best_runner = runner_map[runner_id]

            if best_runner:
                return best_runner, "LAY", f"Lay favorite at {best_price}"

    return None, "", "No selection rule matched"


async def make_shadow_decisions(db: AsyncSession) -> dict[str, Any]:
    """
    Make shadow trading decisions on markets meeting criteria.

    This is the main decision-making function called by the scheduled task.
    """
    config = get_shadow_config()
    stats = {
        "markets_evaluated": 0,
        "decisions_made": 0,
        "skipped_no_rule": 0,
        "skipped_no_selection": 0,
        "skipped_spread_too_wide": 0,
        "errors": 0,
    }

    try:
        # Find tradeable markets
        markets = await find_tradeable_markets(db, config)
        stats["markets_evaluated"] = len(markets)

        for row in markets:
            try:
                market_id = row.market_id
                market_type = row.market_type
                event_id = row.event_id
                score_id = row.score_id
                total_score = Decimal(str(row.total_score))
                scheduled_start = row.scheduled_start
                competition_id = row.competition_id
                competition_name = row.competition_name

                # Check if market type is enabled
                rule = config.get_market_rule(market_type)
                if not rule.enabled:
                    stats["skipped_no_rule"] += 1
                    continue

                # Get runners
                runners_result = await db.execute(
                    select(Runner).where(Runner.market_id == market_id)
                )
                runners = list(runners_result.scalars().all())

                if not runners:
                    stats["skipped_no_selection"] += 1
                    continue

                # Get latest snapshot for prices
                snapshot_result = await db.execute(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.market_id == market_id)
                    .order_by(MarketSnapshot.captured_at.desc())
                    .limit(1)
                )
                latest_snapshot = snapshot_result.scalar_one_or_none()

                # Select runner
                selected_runner, decision_type, reason = select_runner_for_decision(
                    runners, market_type, config, latest_snapshot
                )

                if not selected_runner:
                    stats["skipped_no_selection"] += 1
                    logger.debug(
                        "no_selection",
                        market_id=market_id,
                        market_type=market_type,
                        reason=reason,
                    )
                    continue

                # Get entry prices from snapshot
                entry_back_price = Decimal("0")
                entry_lay_price = Decimal("0")
                available_to_back = Decimal("0")
                available_to_lay = Decimal("0")

                if latest_snapshot and latest_snapshot.ladder_data:
                    for lr in latest_snapshot.ladder_data.get("runners", []):
                        if lr.get("runner_id") == selected_runner.betfair_id:
                            back_prices = lr.get("back", [])
                            lay_prices = lr.get("lay", [])

                            if back_prices:
                                entry_back_price = Decimal(str(back_prices[0].get("price", 0)))
                                available_to_back = Decimal(str(back_prices[0].get("size", 0)))
                            if lay_prices:
                                entry_lay_price = Decimal(str(lay_prices[0].get("price", 0)))
                                available_to_lay = Decimal(str(lay_prices[0].get("size", 0)))
                            break

                # Check spread
                if entry_back_price > 0 and entry_lay_price > 0:
                    spread_pct = ((entry_lay_price - entry_back_price) / entry_back_price) * 100
                    if spread_pct > config.entry.max_spread_percent:
                        stats["skipped_spread_too_wide"] += 1
                        logger.debug(
                            "spread_too_wide",
                            market_id=market_id,
                            spread_pct=float(spread_pct),
                        )
                        continue
                else:
                    spread_pct = Decimal("0")

                # Calculate minutes to start
                now = datetime.now(timezone.utc)
                minutes_to_start = int((scheduled_start - now).total_seconds() / 60)

                # Build niche identifier
                niche = f"{competition_name} - {market_type}"

                # Create shadow decision
                decision = ShadowDecision(
                    market_id=market_id,
                    runner_id=selected_runner.id,
                    decision_type=decision_type,
                    score_id=score_id,
                    trigger_score=total_score,
                    trigger_reason=f"Score {total_score} >= {config.entry.min_score}. {reason}",
                    decision_at=now,
                    minutes_to_start=minutes_to_start,
                    entry_back_price=entry_back_price,
                    entry_lay_price=entry_lay_price,
                    entry_spread=spread_pct,
                    available_to_back=available_to_back,
                    available_to_lay=available_to_lay,
                    theoretical_stake=config.stake.base_stake,
                    outcome="PENDING",
                    niche=niche,
                    competition_id=competition_id,
                )

                db.add(decision)
                stats["decisions_made"] += 1

                logger.info(
                    "shadow_decision_made",
                    market_id=market_id,
                    runner=selected_runner.name,
                    decision_type=decision_type,
                    score=float(total_score),
                    entry_price=float(entry_back_price if decision_type == "BACK" else entry_lay_price),
                    niche=niche,
                )

            except Exception as e:
                logger.error(
                    "decision_error",
                    market_id=row.market_id if hasattr(row, 'market_id') else None,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()

        logger.info("shadow_decisions_complete", **stats)

    except Exception as e:
        logger.error("shadow_decisions_failed", error=str(e))
        await db.rollback()
        raise

    return stats


# =============================================================================
# CLV Capture
# =============================================================================

async def capture_closing_prices(db: AsyncSession) -> dict[str, Any]:
    """
    Update shadow decisions with closing prices for CLV calculation.

    Runs after decisions are made, captures the final prices before kickoff.
    """
    stats = {
        "decisions_checked": 0,
        "closing_prices_captured": 0,
        "errors": 0,
    }

    try:
        now = datetime.now(timezone.utc)

        # Find decisions that need closing prices
        # (have entry prices but no closing prices, market about to start)
        query = text("""
            SELECT
                sd.id AS decision_id,
                sd.market_id,
                sd.runner_id,
                r.betfair_id AS runner_betfair_id,
                e.scheduled_start
            FROM shadow_decisions sd
            JOIN markets m ON sd.market_id = m.id
            JOIN runners r ON sd.runner_id = r.id
            JOIN events e ON m.event_id = e.id
            WHERE
                sd.closing_back_price IS NULL
                AND sd.entry_back_price > 0
                AND e.scheduled_start <= :cutoff
                AND e.scheduled_start > :now_minus_2h
        """)

        result = await db.execute(query, {
            "cutoff": now + timedelta(minutes=5),
            "now_minus_2h": now - timedelta(hours=2),
        })
        decisions = result.fetchall()
        stats["decisions_checked"] = len(decisions)

        for row in decisions:
            try:
                # Get latest snapshot
                snapshot_result = await db.execute(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.market_id == row.market_id)
                    .order_by(MarketSnapshot.captured_at.desc())
                    .limit(1)
                )
                snapshot = snapshot_result.scalar_one_or_none()

                if not snapshot or not snapshot.ladder_data:
                    continue

                # Find runner prices
                for lr in snapshot.ladder_data.get("runners", []):
                    if lr.get("runner_id") == row.runner_betfair_id:
                        back_prices = lr.get("back", [])
                        lay_prices = lr.get("lay", [])

                        if back_prices and lay_prices:
                            closing_back = Decimal(str(back_prices[0].get("price", 0)))
                            closing_lay = Decimal(str(lay_prices[0].get("price", 0)))

                            # Compute closing mid-price for CLV calculation
                            closing_mid = (closing_back + closing_lay) / 2

                            # Get the decision and update
                            decision = await db.get(ShadowDecision, row.decision_id)
                            if decision:
                                decision.closing_back_price = closing_back
                                decision.closing_lay_price = closing_lay
                                decision.closing_mid_price = closing_mid

                                # Calculate CLV vs closing mid-price
                                # Positive CLV = better price than close = pricing skill
                                if decision.decision_type == "BACK" and closing_mid > 0:
                                    # For BACK: higher entry odds than mid = got better price
                                    clv = ((decision.entry_back_price - closing_mid) / closing_mid) * 100
                                elif decision.decision_type == "LAY" and closing_mid > 0:
                                    # For LAY: lower entry odds than mid = got better price
                                    clv = ((closing_mid - decision.entry_lay_price) / decision.entry_lay_price) * 100
                                else:
                                    clv = Decimal("0")

                                decision.clv_percent = clv
                                stats["closing_prices_captured"] += 1

                                logger.debug(
                                    "closing_price_captured",
                                    decision_id=row.decision_id,
                                    closing_mid=float(closing_mid),
                                    clv_percent=float(clv),
                                )
                        break

            except Exception as e:
                logger.error(
                    "closing_price_error",
                    decision_id=row.decision_id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()
        logger.info("closing_prices_complete", **stats)

    except Exception as e:
        logger.error("closing_prices_failed", error=str(e))
        await db.rollback()
        raise

    return stats


# =============================================================================
# Settlement
# =============================================================================

def calculate_pnl(
    stake: Decimal,
    entry_price: Decimal,
    outcome: str,
    decision_type: str,
    commission_rate: Decimal = None,
) -> dict[str, Decimal]:
    """Calculate theoretical P&L for a shadow decision.

    Args:
        commission_rate: If None, uses the single source of truth from
            ShadowTradingConfig.stake.commission_rate. Pass explicitly
            only for testing or what-if analysis.
    """
    if commission_rate is None:
        commission_rate = get_shadow_config().stake.commission_rate

    if outcome == "VOID":
        return {
            "gross_pnl": Decimal("0"),
            "commission": Decimal("0"),
            "spread_cost": Decimal("0"),
            "net_pnl": Decimal("0"),
            "max_loss": Decimal("0"),
            "return_on_risk": Decimal("0"),
        }

    if decision_type == "BACK":
        max_loss = stake
        if outcome == "WIN":
            gross_pnl = stake * (entry_price - 1)
            commission = gross_pnl * commission_rate
            net_pnl = gross_pnl - commission
        else:  # LOSE
            gross_pnl = -stake
            commission = Decimal("0")
            net_pnl = gross_pnl
    else:  # LAY
        max_loss = stake * (entry_price - 1)
        if outcome == "WIN":  # Selection lost, lay wins
            gross_pnl = stake
            commission = gross_pnl * commission_rate
            net_pnl = gross_pnl - commission
        else:  # LOSE (selection won, lay loses)
            gross_pnl = -stake * (entry_price - 1)
            commission = Decimal("0")
            net_pnl = gross_pnl

    # Return on Risk: normalised metric that makes BACK and LAY comparable
    return_on_risk = (net_pnl / max_loss) if max_loss != 0 else Decimal("0")

    return {
        "gross_pnl": gross_pnl,
        "commission": commission,
        "spread_cost": Decimal("0"),  # Could estimate from entry spread
        "net_pnl": net_pnl,
        "max_loss": max_loss,
        "return_on_risk": return_on_risk,
    }


async def settle_shadow_decisions(db: AsyncSession) -> dict[str, Any]:
    """
    Settle shadow decisions based on market results.
    """
    stats = {
        "decisions_checked": 0,
        "settled_win": 0,
        "settled_lose": 0,
        "settled_void": 0,
        "not_yet_settled": 0,
        "errors": 0,
    }

    try:
        # Find pending decisions with markets that may have settled
        query = text("""
            SELECT
                sd.id AS decision_id,
                sd.market_id,
                sd.runner_id,
                sd.decision_type,
                sd.entry_back_price,
                sd.entry_lay_price,
                sd.theoretical_stake,
                r.betfair_id AS runner_betfair_id,
                r.status AS runner_status
            FROM shadow_decisions sd
            JOIN runners r ON sd.runner_id = r.id
            JOIN markets m ON sd.market_id = m.id
            JOIN events e ON m.event_id = e.id
            WHERE
                sd.outcome = 'PENDING'
                AND e.scheduled_start < :cutoff
        """)

        result = await db.execute(query, {
            "cutoff": datetime.now(timezone.utc) - timedelta(hours=2),
        })
        decisions = result.fetchall()
        stats["decisions_checked"] = len(decisions)

        config = get_shadow_config()

        for row in decisions:
            try:
                decision = await db.get(ShadowDecision, row.decision_id)
                if not decision:
                    continue

                # Check runner status
                runner_status = row.runner_status

                if runner_status == "WINNER":
                    if row.decision_type == "BACK":
                        outcome = "WIN"
                    else:  # LAY
                        outcome = "LOSE"
                elif runner_status == "LOSER":
                    if row.decision_type == "BACK":
                        outcome = "LOSE"
                    else:  # LAY
                        outcome = "WIN"
                elif runner_status in ("REMOVED", "REMOVED_VACANT"):
                    outcome = "VOID"
                else:
                    stats["not_yet_settled"] += 1
                    continue

                # Calculate P&L
                entry_price = (
                    row.entry_back_price if row.decision_type == "BACK"
                    else row.entry_lay_price
                )
                pnl = calculate_pnl(
                    stake=Decimal(str(row.theoretical_stake)),
                    entry_price=Decimal(str(entry_price)),
                    outcome=outcome,
                    decision_type=row.decision_type,
                    commission_rate=config.stake.commission_rate,
                )

                # Update decision
                decision.outcome = outcome
                decision.settled_at = datetime.now(timezone.utc)
                decision.gross_pnl = pnl["gross_pnl"]
                decision.commission = pnl["commission"]
                decision.spread_cost = pnl["spread_cost"]
                decision.net_pnl = pnl["net_pnl"]
                decision.max_loss = pnl["max_loss"]
                decision.return_on_risk = pnl["return_on_risk"]

                if outcome == "WIN":
                    stats["settled_win"] += 1
                elif outcome == "LOSE":
                    stats["settled_lose"] += 1
                else:
                    stats["settled_void"] += 1

                logger.info(
                    "shadow_decision_settled",
                    decision_id=row.decision_id,
                    outcome=outcome,
                    net_pnl=float(pnl["net_pnl"]),
                )

            except Exception as e:
                logger.error(
                    "settlement_error",
                    decision_id=row.decision_id,
                    error=str(e),
                )
                stats["errors"] += 1

        await db.commit()
        logger.info("shadow_settlement_complete", **stats)

    except Exception as e:
        logger.error("shadow_settlement_failed", error=str(e))
        await db.rollback()
        raise

    return stats


# =============================================================================
# Celery Task Wrappers
# =============================================================================

@shared_task(name="app.tasks.shadow_trading.make_shadow_decisions_task", queue="odds")
def make_shadow_decisions_task() -> dict[str, Any]:
    """
    Celery task to make shadow trading decisions.

    Runs every 2 minutes when Phase 2 is active.
    """
    async def _run():
        async with get_task_session() as db:
            # Check if we're in Phase 2
            phase, details = await get_current_phase(db)

            if phase != TradingPhase.PHASE2_SHADOW:
                logger.debug(
                    "shadow_trading_not_active",
                    phase=phase.value,
                    details=details,
                )
                return {"status": "skipped", "phase": phase.value, "details": details}

            return await make_shadow_decisions(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.shadow_trading.capture_closing_prices_task", queue="odds")
def capture_closing_prices_task() -> dict[str, Any]:
    """
    Celery task to capture closing prices for CLV.

    Runs every 2 minutes when Phase 2 is active.
    """
    async def _run():
        async with get_task_session() as db:
            phase, _ = await get_current_phase(db)

            if phase != TradingPhase.PHASE2_SHADOW:
                return {"status": "skipped", "phase": phase.value}

            return await capture_closing_prices(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.shadow_trading.settle_shadow_decisions_task", queue="fixtures")
def settle_shadow_decisions_task() -> dict[str, Any]:
    """
    Celery task to settle shadow decisions.

    Runs every 15 minutes when Phase 2 is active.
    """
    async def _run():
        async with get_task_session() as db:
            phase, _ = await get_current_phase(db)

            if phase != TradingPhase.PHASE2_SHADOW:
                return {"status": "skipped", "phase": phase.value}

            return await settle_shadow_decisions(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.shadow_trading.check_phase_status_task", queue="fixtures")
def check_phase_status_task() -> dict[str, Any]:
    """
    Celery task to check and log current phase status.

    Runs hourly to track progress toward Phase 2 activation.
    """
    async def _run():
        async with get_task_session() as db:
            phase, details = await get_current_phase(db)
            logger.info(
                "phase_status_check",
                phase=phase.value,
                details=details,
            )
            return {"phase": phase.value, "details": details}

    return asyncio.run(_run())
