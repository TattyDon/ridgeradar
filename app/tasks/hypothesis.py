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

# =============================================================================
# Default Hypotheses
#
# These hypotheses test different aspects of the strategy document:
# 1. Steam following - does following sharp money movement work?
# 2. Niche markets - are O/U or Correct Score markets more exploitable?
# 3. Structural inefficiencies - do thin markets offer edge?
# 4. Time windows - is 6-24h before kickoff optimal?
# 5. Score validation - does our exploitability score predict outcomes?
#
# IMPORTANT: These run across ALL enabled competitions. Competition-specific
# hypotheses should be created via the Strategy Builder UI.
# =============================================================================

DEFAULT_HYPOTHESES = [
    # -------------------------------------------------------------------------
    # HYPOTHESIS 1: Steam Following
    # Strategy ref: "Sharp money moves first" - test if steam signals work
    # -------------------------------------------------------------------------
    {
        "name": "steam_follower",
        "display_name": "Steam Follower",
        "description": (
            "Backs selections that are steaming (price shortening) >5% in markets "
            "with exploitability score >=30. Tests the core hypothesis that sharp "
            "money moves first in thin markets. Time window: 6-24h (strategy optimal)."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 30,
            "min_price_change_pct": 5.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 360,  # 6 hours - strategy optimal start
            "max_minutes_to_start": 1440,  # 24 hours - strategy optimal end
            "min_total_matched": 5000,  # £5k - strategy minimum
            "max_spread_pct": 5.0,
            "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25", "OVER_UNDER_15"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 2: Pure Momentum (no score validation)
    # Tests if momentum ALONE works without exploitability filtering
    # -------------------------------------------------------------------------
    {
        "name": "strong_steam_pure",
        "display_name": "Strong Steam (Pure Momentum)",
        "description": (
            "Tests pure momentum hypothesis - strong steam (>10%) with NO score "
            "requirement. If this outperforms steam_follower, score adds no value. "
            "If it underperforms, score validation is important."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 0,  # No score requirement - pure momentum test
            "min_price_change_pct": 10.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 360,  # 6h
            "max_minutes_to_start": 1440,  # 24h
            "min_total_matched": 5000,
            "max_spread_pct": 6.0,
            "market_type_filter": ["MATCH_ODDS"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 3: Contrarian Drift Fading
    # Strategy ref: "Overreaction that will correct" in thin markets
    # -------------------------------------------------------------------------
    {
        "name": "drift_fader",
        "display_name": "Drift Fader (Contrarian)",
        "description": (
            "Lays selections drifting >8% in high-score markets. Tests contrarian "
            "hypothesis: drift in thin markets may be overreaction from recreational "
            "money that sharps will correct. Higher risk strategy."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 40,  # Higher threshold for contrarian
            "min_price_change_pct": 8.0,
            "price_change_direction": "drifting",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 360,  # 6h
            "max_minutes_to_start": 1440,  # 24h
            "min_total_matched": 5000,
            "max_spread_pct": 5.0,
            "market_type_filter": ["MATCH_ODDS"],
        },
        "selection_logic": "contrarian",
        "decision_type": "LAY",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 4: Score-Based (Baseline)
    # Tests if exploitability score alone predicts outcomes
    # -------------------------------------------------------------------------
    {
        "name": "score_based_classic",
        "display_name": "Score-Based (Baseline)",
        "description": (
            "Baseline hypothesis: enters on high score (>=50) regardless of momentum. "
            "Tests whether structural inefficiency (score) alone identifies value. "
            "Compare to momentum hypotheses to see if steam adds signal."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 50,  # High score threshold
            "min_price_change_pct": 0,  # No momentum requirement
            "price_change_direction": None,
            "price_change_window_minutes": 0,
            "min_minutes_to_start": 360,  # 6h - aligned with strategy
            "max_minutes_to_start": 1440,  # 24h
            "min_total_matched": 5000,
            "max_spread_pct": 4.0,
            "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25"],
        },
        "selection_logic": "score_based",
        "decision_type": "BACK",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 5: Over/Under Specialist
    # Strategy ref: "Niche market types" - O/U may be less efficient
    # -------------------------------------------------------------------------
    {
        "name": "over_under_specialist",
        "display_name": "Over/Under Specialist",
        "description": (
            "Focuses on O/U markets with steam. Strategy suggests these are 'ignored "
            "vs Match Odds' and may have structural inefficiencies. Tests whether "
            "O/U markets are more exploitable than Match Odds."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 25,  # Lower threshold for niche market
            "min_price_change_pct": 4.0,
            "price_change_direction": "steaming",
            "price_change_window_minutes": 120,
            "min_minutes_to_start": 360,  # 6h
            "max_minutes_to_start": 1440,  # 24h
            "min_total_matched": 3000,  # Lower for niche markets
            "max_spread_pct": 6.0,
            "market_type_filter": ["OVER_UNDER_25", "OVER_UNDER_15", "OVER_UNDER_35"],
        },
        "selection_logic": "momentum",
        "decision_type": "BACK",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 6: Correct Score Specialist
    # Strategy ref: "Correct Score ignored" - test if this creates edge
    # NOTE: We explicitly include CORRECT_SCORE here despite movers page filter
    # -------------------------------------------------------------------------
    {
        "name": "correct_score_value",
        "display_name": "Correct Score Value",
        "description": (
            "Tests Correct Score markets - strategy identifies these as 'ignored'. "
            "Lower liquidity threshold as CS markets are naturally thinner. "
            "High risk/reward - many outcomes but potentially inefficient pricing."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 35,
            "min_price_change_pct": 0,  # No momentum - score-based for CS
            "price_change_direction": None,
            "price_change_window_minutes": 0,
            "min_minutes_to_start": 360,  # 6h
            "max_minutes_to_start": 1440,  # 24h
            "min_total_matched": 1000,  # Lower threshold - CS is thinner
            "max_spread_pct": 8.0,  # Wider spread tolerance for CS
            "min_price": 3.0,  # Avoid very short prices
            "max_price": 30.0,  # Avoid extreme longshots
            "market_type_filter": ["CORRECT_SCORE"],
        },
        "selection_logic": "score_based",
        "decision_type": "BACK",
    },

    # -------------------------------------------------------------------------
    # HYPOTHESIS 7: Shallow Market Test
    # Strategy ref: "Too small for institutions" - test if edge exists
    # -------------------------------------------------------------------------
    {
        "name": "shallow_market_edge",
        "display_name": "Shallow Market Edge",
        "description": (
            "Tests the 'shallow market' hypothesis - markets with £1k-£5k matched "
            "may be ignored by institutions but still tradeable. Higher score "
            "threshold required due to lower liquidity reliability."
        ),
        "enabled": True,
        "entry_criteria": {
            "min_score": 45,  # Higher threshold for thin markets
            "min_price_change_pct": 0,  # Score-based, not momentum
            "price_change_direction": None,
            "price_change_window_minutes": 0,
            "min_minutes_to_start": 360,
            "max_minutes_to_start": 1440,
            "min_total_matched": 1000,  # Low liquidity threshold
            "max_total_matched": 5000,  # CAP at £5k - only shallow markets
            "max_spread_pct": 7.0,  # Accept wider spreads
            "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25"],
        },
        "selection_logic": "score_based",
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
