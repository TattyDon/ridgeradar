"""Shadow Trading API Endpoints.

Provides endpoints for monitoring and managing the Phase 2 shadow trading system.

IMPORTANT: This is PAPER TRADING only. All P&L figures are theoretical.
No real money is ever at risk.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db

logger = structlog.get_logger(__name__)
from app.config.shadow_trading import TradingPhase, get_shadow_config
from app.models.domain import (
    Competition,
    Event,
    Market,
    Runner,
    ShadowDecision,
)

router = APIRouter(prefix="/api/shadow", tags=["shadow-trading"])


# =============================================================================
# Response Models
# =============================================================================

class PhaseStatus(BaseModel):
    """Current trading phase status."""
    phase: str
    phase_display: str
    is_paper_trading: bool
    real_money_at_risk: bool
    auto_activated: bool
    thresholds: dict
    config_summary: dict


class ShadowPerformance(BaseModel):
    """Aggregate shadow trading performance."""
    mode: str  # Always "PAPER"
    real_money_at_risk: bool  # Always False

    total_decisions: int
    pending_decisions: int
    settled_decisions: int

    wins: int
    losses: int
    voids: int
    win_rate: float

    gross_pnl: float
    total_commission: float
    net_pnl: float

    avg_stake: float
    avg_clv_percent: float
    positive_clv_rate: float

    best_niche: Optional[str]
    worst_niche: Optional[str]

    disclaimer: str


class ShadowDecisionItem(BaseModel):
    """Individual shadow decision."""
    id: int
    decision_at: str
    competition: str
    event: str
    market_type: str
    runner: str
    decision_type: str
    trigger_score: float
    entry_price: float
    closing_price: Optional[float]
    clv_percent: Optional[float]
    outcome: str
    net_pnl: Optional[float]
    niche: str
    minutes_to_start: int


class NichePerformanceItem(BaseModel):
    """Performance breakdown by niche."""
    niche: str
    competition: str
    market_type: str
    total_decisions: int
    wins: int
    losses: int
    win_rate: float
    avg_clv: float
    net_pnl: float
    roi_percent: float


class CLVCorrelation(BaseModel):
    """CLV correlation with outcomes."""
    clv_band: str
    total_decisions: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl: float


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/status", response_model=PhaseStatus)
async def get_phase_status(db: AsyncSession = Depends(get_db)):
    """
    Get current trading phase status.

    Shows whether shadow trading is active and threshold progress.
    """
    try:
        config = get_shadow_config()

        # Get current data counts - use COALESCE to handle empty tables
        query = text("""
            SELECT
                COALESCE(COUNT(*), 0) AS total_closing_data,
                COALESCE(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0) AS total_with_results,
                COALESCE(COUNT(*) FILTER (WHERE final_score >= 30), 0) AS high_score_markets,
                COALESCE(EXTRACT(DAY FROM (MAX(created_at) - MIN(created_at))) + 1, 0) AS days_collecting
            FROM market_closing_data
        """)

        result = await db.execute(query)
        row = result.one()

        closing_data = row.total_closing_data or 0
        results = row.total_with_results or 0
        high_score = row.high_score_markets or 0
        days = int(row.days_collecting or 0)

        ready, threshold_details = config.activation.check_ready(
            closing_data=closing_data,
            results=results,
            high_score=high_score,
            days=days
        )

        if ready and config.auto_activate_phase2:
            phase = TradingPhase.PHASE2_SHADOW
        else:
            phase = TradingPhase.PHASE1_COLLECTING

        phase_display = {
            TradingPhase.PHASE1_COLLECTING: "Phase 1: Data Collection",
            TradingPhase.PHASE2_SHADOW: "Phase 2: Shadow Trading (Paper)",
            TradingPhase.PHASE3_LIVE: "Phase 3: Live Trading",
        }

        return PhaseStatus(
            phase=phase.value,
            phase_display=phase_display[phase],
            is_paper_trading=phase == TradingPhase.PHASE2_SHADOW,
            real_money_at_risk=False,  # ALWAYS false for shadow trading
            auto_activated=ready and config.auto_activate_phase2,
            thresholds=threshold_details,
            config_summary={
                "min_score": float(config.entry.min_score),
                "base_stake": float(config.stake.base_stake),
                "enabled_market_types": [
                    mt for mt, rule in config.market_rules.items() if rule.enabled
                ],
            },
        )
    except Exception as e:
        logger.error("shadow_status_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Failed to fetch status: {str(e)}")


@router.get("/performance", response_model=ShadowPerformance)
async def get_performance(db: AsyncSession = Depends(get_db)):
    """
    Get aggregate shadow trading performance.

    All figures are THEORETICAL - no real money at risk.
    """
    try:
        query = text("""
            WITH stats AS (
                SELECT
                    COUNT(*) AS total_decisions,
                    COUNT(*) FILTER (WHERE outcome = 'PENDING') AS pending,
                    COUNT(*) FILTER (WHERE outcome IN ('WIN', 'LOSE', 'VOID')) AS settled,
                    COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
                    COUNT(*) FILTER (WHERE outcome = 'LOSE') AS losses,
                    COUNT(*) FILTER (WHERE outcome = 'VOID') AS voids,
                    COALESCE(SUM(gross_pnl), 0) AS gross_pnl,
                    COALESCE(SUM(commission), 0) AS total_commission,
                    COALESCE(SUM(net_pnl), 0) AS net_pnl,
                    AVG(theoretical_stake) AS avg_stake,
                    AVG(clv_percent) FILTER (WHERE clv_percent IS NOT NULL) AS avg_clv,
                    COUNT(*) FILTER (WHERE clv_percent > 0) AS positive_clv_count,
                    COUNT(*) FILTER (WHERE clv_percent IS NOT NULL) AS clv_total
                FROM shadow_decisions
            ),
            best_niche AS (
                SELECT niche, SUM(net_pnl) AS niche_pnl
                FROM shadow_decisions
                WHERE outcome IN ('WIN', 'LOSE')
                GROUP BY niche
                ORDER BY SUM(net_pnl) DESC
                LIMIT 1
            ),
            worst_niche AS (
                SELECT niche, SUM(net_pnl) AS niche_pnl
                FROM shadow_decisions
                WHERE outcome IN ('WIN', 'LOSE')
                GROUP BY niche
                ORDER BY SUM(net_pnl) ASC
                LIMIT 1
            )
            SELECT
                s.*,
                bn.niche AS best_niche,
                wn.niche AS worst_niche
            FROM stats s
            LEFT JOIN best_niche bn ON true
            LEFT JOIN worst_niche wn ON true
        """)

        result = await db.execute(query)
        row = result.one()

        total = row.total_decisions or 0
        wins = row.wins or 0
        losses = row.losses or 0
        settled = wins + losses
        win_rate = (wins / settled * 100) if settled > 0 else 0.0

        clv_total = row.clv_total or 0
        positive_clv = row.positive_clv_count or 0
        positive_clv_rate = (positive_clv / clv_total * 100) if clv_total > 0 else 0.0

        return ShadowPerformance(
            mode="PAPER",
            real_money_at_risk=False,
            total_decisions=total,
            pending_decisions=row.pending or 0,
            settled_decisions=row.settled or 0,
            wins=wins,
            losses=losses,
            voids=row.voids or 0,
            win_rate=round(win_rate, 1),
            gross_pnl=float(row.gross_pnl or 0),
            total_commission=float(row.total_commission or 0),
            net_pnl=float(row.net_pnl or 0),
            avg_stake=float(row.avg_stake or 10),
            avg_clv_percent=float(row.avg_clv or 0),
            positive_clv_rate=round(positive_clv_rate, 1),
            best_niche=row.best_niche,
            worst_niche=row.worst_niche,
            disclaimer="PAPER TRADING: All figures are theoretical. No real money at risk.",
        )
    except Exception as e:
        logger.error("shadow_performance_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Failed to fetch performance: {str(e)}")


@router.get("/decisions")
async def get_decisions(
    db: AsyncSession = Depends(get_db),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
    niche: Optional[str] = Query(None, description="Filter by niche"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get recent shadow decisions.

    All decisions are HYPOTHETICAL - no real trades were executed.
    """
    try:
        # Build query dynamically to avoid asyncpg type inference issues with NULL
        where_clauses = []
        params = {"limit": limit}

        if outcome:
            where_clauses.append("sd.outcome = :outcome")
            params["outcome"] = outcome
        if niche:
            where_clauses.append("sd.niche = :niche")
            params["niche"] = niche

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = text(f"""
            SELECT
                sd.id,
                sd.decision_at,
                c.name AS competition,
                e.name AS event,
                m.market_type,
                r.name AS runner,
                sd.decision_type,
                sd.trigger_score,
                sd.entry_back_price,
                sd.entry_lay_price,
                sd.closing_back_price,
                sd.closing_lay_price,
                sd.clv_percent,
                sd.outcome,
                sd.net_pnl,
                sd.niche,
                sd.minutes_to_start
            FROM shadow_decisions sd
            JOIN markets m ON sd.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            JOIN runners r ON sd.runner_id = r.id
            {where_sql}
            ORDER BY sd.decision_at DESC
            LIMIT :limit
        """)

        result = await db.execute(query, params)
        rows = result.fetchall()

        # Return empty list if no decisions yet
        if not rows:
            logger.info("shadow_decisions_empty", outcome=outcome, niche=niche)
            return []

        return [
            ShadowDecisionItem(
                id=row.id,
                decision_at=row.decision_at.isoformat(),
                competition=row.competition,
                event=row.event,
                market_type=row.market_type,
                runner=row.runner or "Unknown",
                decision_type=row.decision_type,
                trigger_score=float(row.trigger_score),
                entry_price=float(
                    row.entry_back_price if row.decision_type == "BACK"
                    else row.entry_lay_price
                ),
                closing_price=float(
                    row.closing_back_price if row.decision_type == "BACK"
                    else row.closing_lay_price
                ) if row.closing_back_price else None,
                clv_percent=float(row.clv_percent) if row.clv_percent else None,
                outcome=row.outcome or "PENDING",
                net_pnl=float(row.net_pnl) if row.net_pnl else None,
                niche=row.niche or "",
                minutes_to_start=row.minutes_to_start or 0,
            )
            for row in rows
        ]
    except Exception as e:
        logger.error("shadow_decisions_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Failed to fetch decisions: {str(e)}")


@router.get("/niche-performance", response_model=list[NichePerformanceItem])
async def get_niche_performance(
    db: AsyncSession = Depends(get_db),
    min_decisions: int = Query(5, description="Minimum decisions to include"),
    limit: int = Query(20, ge=1, le=50),
):
    """
    Get performance breakdown by niche.

    Identifies which competition + market type combinations perform best.
    """
    query = text("""
        WITH niche_stats AS (
            SELECT
                sd.niche,
                c.name AS competition,
                m.market_type,
                COUNT(*) AS total_decisions,
                COUNT(*) FILTER (WHERE sd.outcome = 'WIN') AS wins,
                COUNT(*) FILTER (WHERE sd.outcome = 'LOSE') AS losses,
                AVG(sd.clv_percent) FILTER (WHERE sd.clv_percent IS NOT NULL) AS avg_clv,
                COALESCE(SUM(sd.net_pnl), 0) AS net_pnl,
                COALESCE(SUM(sd.theoretical_stake), 0) AS total_staked
            FROM shadow_decisions sd
            JOIN markets m ON sd.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            WHERE sd.outcome IN ('WIN', 'LOSE')
            GROUP BY sd.niche, c.name, m.market_type
            HAVING COUNT(*) >= :min_decisions
        )
        SELECT
            niche,
            competition,
            market_type,
            total_decisions,
            wins,
            losses,
            ROUND(wins::numeric / NULLIF(total_decisions, 0) * 100, 1) AS win_rate,
            ROUND(COALESCE(avg_clv, 0)::numeric, 2) AS avg_clv,
            ROUND(net_pnl::numeric, 2) AS net_pnl,
            ROUND(net_pnl / NULLIF(total_staked, 0) * 100, 2) AS roi_percent
        FROM niche_stats
        ORDER BY net_pnl DESC
        LIMIT :limit
    """)

    result = await db.execute(query, {
        "min_decisions": min_decisions,
        "limit": limit,
    })
    rows = result.fetchall()

    return [
        NichePerformanceItem(
            niche=row.niche or "",
            competition=row.competition,
            market_type=row.market_type,
            total_decisions=row.total_decisions,
            wins=row.wins,
            losses=row.losses,
            win_rate=float(row.win_rate or 0),
            avg_clv=float(row.avg_clv or 0),
            net_pnl=float(row.net_pnl or 0),
            roi_percent=float(row.roi_percent or 0),
        )
        for row in rows
    ]


@router.get("/clv-correlation", response_model=list[CLVCorrelation])
async def get_clv_correlation(db: AsyncSession = Depends(get_db)):
    """
    Get CLV correlation with outcomes.

    Shows whether positive CLV correlates with winning trades.
    This is the KEY validation metric for the scoring system.
    """
    query = text("""
        WITH clv_bands AS (
            SELECT
                id,
                outcome,
                net_pnl,
                clv_percent,
                CASE
                    WHEN clv_percent >= 3 THEN 'Strong Positive (3%+)'
                    WHEN clv_percent >= 1 THEN 'Positive (1-3%)'
                    WHEN clv_percent >= 0 THEN 'Slight Positive (0-1%)'
                    WHEN clv_percent >= -1 THEN 'Slight Negative (-1-0%)'
                    ELSE 'Negative (<-1%)'
                END AS clv_band
            FROM shadow_decisions
            WHERE
                clv_percent IS NOT NULL
                AND outcome IN ('WIN', 'LOSE')
        )
        SELECT
            clv_band,
            COUNT(*) AS total_decisions,
            COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE outcome = 'LOSE') AS losses,
            ROUND(
                COUNT(*) FILTER (WHERE outcome = 'WIN')::numeric /
                NULLIF(COUNT(*), 0) * 100, 1
            ) AS win_rate,
            ROUND(AVG(net_pnl)::numeric, 2) AS avg_pnl
        FROM clv_bands
        GROUP BY clv_band
        ORDER BY
            CASE clv_band
                WHEN 'Strong Positive (3%+)' THEN 1
                WHEN 'Positive (1-3%)' THEN 2
                WHEN 'Slight Positive (0-1%)' THEN 3
                WHEN 'Slight Negative (-1-0%)' THEN 4
                ELSE 5
            END
    """)

    result = await db.execute(query)
    rows = result.fetchall()

    return [
        CLVCorrelation(
            clv_band=row.clv_band,
            total_decisions=row.total_decisions,
            wins=row.wins,
            losses=row.losses,
            win_rate=float(row.win_rate or 0),
            avg_pnl=float(row.avg_pnl or 0),
        )
        for row in rows
    ]


@router.get("/daily-pnl")
async def get_daily_pnl(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
):
    """
    Get daily P&L for charting.

    All figures are THEORETICAL.
    """
    query = text(f"""
        SELECT
            DATE(decision_at) AS date,
            COUNT(*) AS decisions,
            COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
            COUNT(*) FILTER (WHERE outcome = 'LOSE') AS losses,
            COALESCE(SUM(net_pnl), 0) AS net_pnl,
            SUM(SUM(net_pnl)) OVER (ORDER BY DATE(decision_at)) AS cumulative_pnl
        FROM shadow_decisions
        WHERE
            decision_at >= CURRENT_DATE - INTERVAL '{days} days'
            AND outcome IN ('WIN', 'LOSE')
        GROUP BY DATE(decision_at)
        ORDER BY DATE(decision_at)
    """)

    result = await db.execute(query)
    rows = result.fetchall()

    return {
        "mode": "PAPER",
        "disclaimer": "Theoretical results only",
        "data": [
            {
                "date": row.date.isoformat(),
                "decisions": row.decisions,
                "wins": row.wins,
                "losses": row.losses,
                "net_pnl": float(row.net_pnl),
                "cumulative_pnl": float(row.cumulative_pnl) if row.cumulative_pnl else 0,
            }
            for row in rows
        ],
    }
