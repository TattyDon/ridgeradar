"""Hypothesis Evaluation Tasks.

Celery tasks for evaluating trading hypotheses and creating shadow decisions.
Supports multiple concurrent hypotheses with different entry criteria.

This is PAPER TRADING only. No real money is ever at risk.
"""

import asyncio
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import select

from app.config.shadow_trading import TradingPhase, get_shadow_config
from app.models.base import get_task_session
from app.models.domain import TradingHypothesis
from app.services.hypothesis_engine import evaluate_all_hypotheses
from app.tasks.shadow_trading import get_current_phase

logger = structlog.get_logger(__name__)


# =============================================================================
# Default Hypotheses
# =============================================================================

DEFAULT_HYPOTHESES = [
    {
        "name": "steam_follower",
        "display_name": "Steam Follower",
        "description": (
            "Backs selections that are steaming (price shortening) significantly "
            "in markets with high exploitability scores. Theory: Sharp money moves "
            "first, so following early steam in thin markets captures value before "
            "the market fully adjusts."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 30,
            "min_price_change_pct": 5.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 60,
            "max_minutes_to_start": 1440,  # 24 hours
            "min_total_matched": 5000,
            "max_spread_pct": 5.0,
            "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25", "OVER_UNDER_15"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },
    {
        "name": "strong_steam_follower",
        "display_name": "Strong Steam Follower",
        "description": (
            "More aggressive steam following - requires stronger price movement "
            "(>10%) but lower score threshold. Tests whether momentum alone is "
            "a sufficient signal without score validation."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 0,  # No score requirement
            "min_price_change_pct": 10.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 60,
            "max_minutes_to_start": 1440,
            "min_total_matched": 3000,
            "max_spread_pct": 6.0,
            "market_type_filter": ["MATCH_ODDS"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },
    {
        "name": "drift_fader",
        "display_name": "Drift Fader",
        "description": (
            "Lays selections that are drifting (price lengthening) significantly "
            "in thin markets. Theory: In low-liquidity markets, drift may represent "
            "overreaction that will correct. Contrarian approach."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 40,
            "min_price_change_pct": 8.0,
            "price_change_direction": "drifting",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 60,
            "max_minutes_to_start": 1440,
            "min_total_matched": 5000,
            "max_spread_pct": 5.0,
            "market_type_filter": ["MATCH_ODDS"],
        },
        "selection_logic": "contrarian",
        "decision_type": "LAY",
    },
    {
        "name": "score_based_classic",
        "display_name": "Score-Based Classic",
        "description": (
            "Original score-based approach: enters when exploitability score "
            "exceeds threshold regardless of momentum. Baseline for comparison "
            "with momentum-based hypotheses."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 50,
            "min_price_change_pct": 0,  # No momentum requirement
            "price_change_direction": None,
            "price_change_window_minutes": 0,
            "min_minutes_to_start": 30,
            "max_minutes_to_start": 480,  # 8 hours
            "min_total_matched": 5000,
            "max_spread_pct": 4.0,
            "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25"],
        },
        "selection_logic": "score_based",
        "decision_type": "BACK",
    },
    {
        "name": "under_specialist",
        "display_name": "Under Goals Specialist",
        "description": (
            "Focuses exclusively on Under goals markets with steam signals. "
            "Tests whether steam in Over/Under markets is more predictive "
            "than in Match Odds."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 25,
            "min_price_change_pct": 4.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 120,
            "max_minutes_to_start": 1440,
            "min_total_matched": 3000,
            "max_spread_pct": 6.0,
            "market_type_filter": ["OVER_UNDER_25", "OVER_UNDER_15", "OVER_UNDER_35"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },
]


async def seed_default_hypotheses(db) -> dict[str, Any]:
    """
    Seed the default trading hypotheses into the database.

    Only creates hypotheses that don't already exist (by name).
    """
    stats = {"created": 0, "existing": 0, "errors": 0}

    for hypothesis_data in DEFAULT_HYPOTHESES:
        try:
            # Check if exists
            result = await db.execute(
                select(TradingHypothesis).where(
                    TradingHypothesis.name == hypothesis_data["name"]
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                stats["existing"] += 1
                logger.debug(
                    "hypothesis_exists",
                    name=hypothesis_data["name"],
                )
                continue

            # Create new hypothesis
            hypothesis = TradingHypothesis(
                name=hypothesis_data["name"],
                display_name=hypothesis_data["display_name"],
                description=hypothesis_data["description"],
                enabled=hypothesis_data["enabled"],
                entry_criteria=hypothesis_data["entry_criteria"],
                selection_logic=hypothesis_data["selection_logic"],
                decision_type=hypothesis_data["decision_type"],
            )
            db.add(hypothesis)
            stats["created"] += 1

            logger.info(
                "hypothesis_created",
                name=hypothesis_data["name"],
            )

        except Exception as e:
            logger.error(
                "hypothesis_seed_error",
                name=hypothesis_data.get("name"),
                error=str(e),
            )
            stats["errors"] += 1

    await db.commit()
    logger.info("hypothesis_seeding_complete", **stats)
    return stats


# =============================================================================
# Celery Tasks
# =============================================================================

@shared_task(name="app.tasks.hypothesis.seed_hypotheses_task", queue="fixtures")
def seed_hypotheses_task() -> dict[str, Any]:
    """
    Celery task to seed default trading hypotheses.

    Run once during setup or after schema migration.
    """
    async def _run():
        async with get_task_session() as db:
            return await seed_default_hypotheses(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.hypothesis.evaluate_hypotheses_task", queue="odds")
def evaluate_hypotheses_task() -> dict[str, Any]:
    """
    Celery task to evaluate all active hypotheses.

    Runs every 2 minutes when Phase 2 is active.
    Finds momentum signals and creates shadow decisions for matching hypotheses.
    """
    async def _run():
        async with get_task_session() as db:
            # Check if we're in Phase 2
            phase, details = await get_current_phase(db)

            if phase != TradingPhase.PHASE2_SHADOW:
                logger.debug(
                    "hypothesis_evaluation_skipped",
                    phase=phase.value,
                    reason="Not in Phase 2",
                )
                return {"status": "skipped", "phase": phase.value, "details": details}

            return await evaluate_all_hypotheses(db)

    return asyncio.run(_run())


@shared_task(name="app.tasks.hypothesis.update_hypothesis_stats_task", queue="fixtures")
def update_hypothesis_stats_task() -> dict[str, Any]:
    """
    Celery task to update denormalized hypothesis statistics.

    Runs hourly to aggregate performance stats for each hypothesis.
    """
    async def _run():
        async with get_task_session() as db:
            from sqlalchemy import text

            # Update stats for each hypothesis
            query = text("""
                UPDATE trading_hypotheses h
                SET
                    total_decisions = sub.total_decisions,
                    total_wins = sub.total_wins,
                    total_losses = sub.total_losses,
                    total_pnl = sub.total_pnl,
                    avg_clv = sub.avg_clv,
                    last_decision_at = sub.last_decision_at
                FROM (
                    SELECT
                        hypothesis_id,
                        COUNT(*) AS total_decisions,
                        COUNT(*) FILTER (WHERE outcome = 'WIN') AS total_wins,
                        COUNT(*) FILTER (WHERE outcome = 'LOSE') AS total_losses,
                        COALESCE(SUM(net_pnl), 0) AS total_pnl,
                        AVG(clv_percent) FILTER (WHERE clv_percent IS NOT NULL) AS avg_clv,
                        MAX(decision_at) AS last_decision_at
                    FROM shadow_decisions
                    WHERE hypothesis_id IS NOT NULL
                    GROUP BY hypothesis_id
                ) sub
                WHERE h.id = sub.hypothesis_id
            """)

            await db.execute(query)
            await db.commit()

            logger.info("hypothesis_stats_updated")
            return {"status": "success"}

    return asyncio.run(_run())
