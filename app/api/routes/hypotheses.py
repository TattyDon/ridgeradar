"""Trading Hypothesis API Endpoints.

Provides endpoints for managing and analyzing trading hypotheses.
Each hypothesis represents a specific trading strategy being tested.

IMPORTANT: This is PAPER TRADING only. All results are theoretical.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.domain import TradingHypothesis, ShadowDecision

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/hypotheses", tags=["hypotheses"])


# =============================================================================
# Response Models
# =============================================================================

class HypothesisSummary(BaseModel):
    """Summary of a trading hypothesis."""
    id: int
    name: str
    display_name: str
    description: str
    enabled: bool
    selection_logic: str
    decision_type: str

    # Entry criteria summary
    min_score: float
    min_price_change_pct: float
    price_change_direction: Optional[str]
    time_window: str  # e.g., "1h-24h before kickoff"

    # Performance stats
    total_decisions: int
    wins: int
    losses: int
    pending: int
    win_rate: float
    total_pnl: float
    avg_clv: Optional[float]
    roi_percent: float

    # Activity
    last_decision_at: Optional[str]
    created_at: str


class HypothesisDetail(HypothesisSummary):
    """Detailed view of a hypothesis including full entry criteria."""
    entry_criteria: dict


class HypothesisComparison(BaseModel):
    """Compare performance across hypotheses."""
    hypothesis_name: str
    display_name: str
    total_decisions: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_clv: float
    avg_return_on_risk: float  # Normalised: net_pnl / max_loss (makes BACK/LAY comparable)
    roi_percent: float
    sharpe_estimate: Optional[float]  # Rough estimate
    is_profitable: bool
    verdict: str  # "PROMISING", "MARGINAL", "UNPROFITABLE", "INSUFFICIENT_DATA", "WARNING_NEGATIVE_CLV"
    multiple_testing_warning: Optional[str] = None  # Warn when >3 hypotheses compared


class HypothesisDecision(BaseModel):
    """A decision made by a specific hypothesis."""
    id: int
    decision_at: str
    competition: str
    event: str
    market_type: str
    runner: str
    decision_type: str
    trigger_score: float
    entry_price: float
    price_change_1h: Optional[float]
    price_change_2h: Optional[float]
    closing_price: Optional[float]
    clv_percent: Optional[float]
    outcome: str
    net_pnl: Optional[float]


class HypothesisCreate(BaseModel):
    """Request model for creating a new hypothesis."""
    name: str  # snake_case identifier
    display_name: str  # Human-readable name
    description: str
    selection_logic: str = "HIGHEST_SCORE"  # HIGHEST_SCORE, BEST_VALUE, SPECIFIC_RUNNER
    decision_type: str = "BACK"  # BACK or LAY
    enabled: bool = True

    # Entry criteria
    min_score: float = 30.0
    min_price_change_pct: float = 0.0
    price_change_direction: Optional[str] = None  # "steaming", "drifting", or None
    min_minutes_to_start: int = 60
    max_minutes_to_start: int = 1440
    market_types: Optional[list[str]] = None  # e.g., ["OVER_UNDER_25"], None means all
    min_price: float = 1.10
    max_price: float = 10.0


class HypothesisUpdate(BaseModel):
    """Request model for updating an existing hypothesis."""
    display_name: Optional[str] = None
    description: Optional[str] = None
    selection_logic: Optional[str] = None
    decision_type: Optional[str] = None
    enabled: Optional[bool] = None

    # Entry criteria
    min_score: Optional[float] = None
    min_price_change_pct: Optional[float] = None
    price_change_direction: Optional[str] = None
    min_minutes_to_start: Optional[int] = None
    max_minutes_to_start: Optional[int] = None
    market_types: Optional[list[str]] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/", response_model=list[HypothesisSummary])
async def list_hypotheses(
    db: AsyncSession = Depends(get_db),
    enabled_only: bool = Query(False, description="Only show enabled hypotheses"),
):
    """
    List all trading hypotheses with their current performance stats.
    """
    try:
        # Build query with stats
        query = text("""
            SELECT
                h.id,
                h.name,
                h.display_name,
                h.description,
                h.enabled,
                h.selection_logic,
                h.decision_type,
                h.entry_criteria,
                h.created_at,
                COALESCE(h.total_decisions, 0) as total_decisions,
                COALESCE(h.total_wins, 0) as wins,
                COALESCE(h.total_losses, 0) as losses,
                COALESCE(h.total_pnl, 0) as total_pnl,
                h.avg_clv,
                h.last_decision_at,
                -- Count pending separately
                COALESCE(pending.count, 0) as pending_count
            FROM trading_hypotheses h
            LEFT JOIN (
                SELECT hypothesis_id, COUNT(*) as count
                FROM shadow_decisions
                WHERE outcome = 'PENDING'
                GROUP BY hypothesis_id
            ) pending ON h.id = pending.hypothesis_id
            WHERE (:enabled_only = false OR h.enabled = true)
            ORDER BY h.total_pnl DESC NULLS LAST, h.name
        """)

        result = await db.execute(query, {"enabled_only": enabled_only})
        rows = result.fetchall()

        hypotheses = []
        for row in rows:
            criteria = row.entry_criteria or {}
            settled = row.wins + row.losses

            # Format time window
            min_mins = criteria.get("min_minutes_to_start", 0)
            max_mins = criteria.get("max_minutes_to_start", 1440)
            time_window = f"{min_mins//60}h-{max_mins//60}h before kickoff"

            # Calculate ROI
            total_staked = row.total_decisions * 10 if row.total_decisions > 0 else 1
            roi = float(row.total_pnl) / total_staked * 100

            hypotheses.append(HypothesisSummary(
                id=row.id,
                name=row.name,
                display_name=row.display_name,
                description=row.description,
                enabled=row.enabled,
                selection_logic=row.selection_logic,
                decision_type=row.decision_type,
                min_score=criteria.get("min_score", 0),
                min_price_change_pct=criteria.get("min_price_change_pct", 0),
                price_change_direction=criteria.get("price_change_direction"),
                time_window=time_window,
                total_decisions=row.total_decisions,
                wins=row.wins,
                losses=row.losses,
                pending=row.pending_count,
                win_rate=round(row.wins / settled * 100, 1) if settled > 0 else 0.0,
                total_pnl=float(row.total_pnl),
                avg_clv=float(row.avg_clv) if row.avg_clv else None,
                roi_percent=round(roi, 2),
                last_decision_at=row.last_decision_at.isoformat() if row.last_decision_at else None,
                created_at=row.created_at.isoformat(),
            ))

        return hypotheses

    except Exception as e:
        logger.error("list_hypotheses_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compare", response_model=list[HypothesisComparison])
async def compare_hypotheses(
    db: AsyncSession = Depends(get_db),
    min_decisions: int = Query(20, description="Minimum decisions for comparison"),
):
    """
    Compare performance across all hypotheses.

    Only includes hypotheses with sufficient decisions for meaningful comparison.
    """
    try:
        query = text("""
            WITH hypothesis_stats AS (
                SELECT
                    h.name as hypothesis_name,
                    h.display_name,
                    COUNT(*) as total_decisions,
                    COUNT(*) FILTER (WHERE sd.outcome = 'WIN') as wins,
                    COUNT(*) FILTER (WHERE sd.outcome = 'LOSE') as losses,
                    COALESCE(SUM(sd.net_pnl), 0) as total_pnl,
                    AVG(sd.clv_percent) FILTER (WHERE sd.clv_percent IS NOT NULL) as avg_clv,
                    AVG(sd.return_on_risk) FILTER (WHERE sd.return_on_risk IS NOT NULL) as avg_return_on_risk,
                    STDDEV(sd.net_pnl) FILTER (WHERE sd.outcome IN ('WIN', 'LOSE')) as pnl_stddev,
                    AVG(sd.net_pnl) FILTER (WHERE sd.outcome IN ('WIN', 'LOSE')) as avg_pnl
                FROM trading_hypotheses h
                LEFT JOIN shadow_decisions sd ON h.id = sd.hypothesis_id
                    AND sd.outcome IN ('WIN', 'LOSE', 'PENDING')
                GROUP BY h.id, h.name, h.display_name
                HAVING COUNT(*) FILTER (WHERE sd.outcome IN ('WIN', 'LOSE')) >= :min_decisions
            )
            SELECT
                *,
                CASE
                    WHEN pnl_stddev > 0 AND avg_pnl IS NOT NULL
                    THEN avg_pnl / pnl_stddev * SQRT(252)  -- Annualized approximation
                    ELSE NULL
                END as sharpe_estimate
            FROM hypothesis_stats
            ORDER BY total_pnl DESC
        """)

        result = await db.execute(query, {"min_decisions": min_decisions})
        rows = result.fetchall()

        # Multiple testing warning when >3 hypotheses compared
        num_hypotheses = len(rows)
        multiple_testing_warning = None
        if num_hypotheses > 3:
            corrected_alpha = round(0.05 / num_hypotheses, 3)
            multiple_testing_warning = (
                f"Comparing {num_hypotheses} hypotheses simultaneously. "
                f"Selection bias risk: recommend time-split holdout validation "
                f"and Bonferroni-corrected significance threshold (alpha = {corrected_alpha})."
            )

        comparisons = []
        for row in rows:
            settled = row.wins + row.losses
            win_rate = row.wins / settled * 100 if settled > 0 else 0
            total_staked = settled * 10
            roi = float(row.total_pnl) / total_staked * 100 if total_staked > 0 else 0
            is_profitable = float(row.total_pnl) > 0
            avg_clv_val = float(row.avg_clv or 0)
            avg_ror = float(row.avg_return_on_risk) if row.avg_return_on_risk else 0.0

            # Determine verdict (CLV is now a primary signal)
            if settled < 50:
                verdict = "INSUFFICIENT_DATA"
            elif settled >= 100 and avg_clv_val < -1.0:
                verdict = "WARNING_NEGATIVE_CLV"
            elif roi > 3 and avg_clv_val > 0:
                verdict = "PROMISING"
            elif roi > 0 and avg_clv_val > 0:
                verdict = "MARGINAL"
            elif roi > 0:
                verdict = "MARGINAL"
            else:
                verdict = "UNPROFITABLE"

            comparisons.append(HypothesisComparison(
                hypothesis_name=row.hypothesis_name,
                display_name=row.display_name,
                total_decisions=row.total_decisions,
                wins=row.wins,
                losses=row.losses,
                win_rate=round(win_rate, 1),
                total_pnl=float(row.total_pnl),
                avg_clv=avg_clv_val,
                avg_return_on_risk=round(avg_ror, 4),
                roi_percent=round(roi, 2),
                sharpe_estimate=round(float(row.sharpe_estimate), 2) if row.sharpe_estimate else None,
                is_profitable=is_profitable,
                verdict=verdict,
                multiple_testing_warning=multiple_testing_warning,
            ))

        return comparisons

    except Exception as e:
        logger.error("compare_hypotheses_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{hypothesis_name}", response_model=HypothesisDetail)
async def get_hypothesis(
    hypothesis_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific hypothesis.
    """
    try:
        result = await db.execute(
            select(TradingHypothesis).where(TradingHypothesis.name == hypothesis_name)
        )
        hypothesis = result.scalar_one_or_none()

        if not hypothesis:
            raise HTTPException(status_code=404, detail=f"Hypothesis '{hypothesis_name}' not found")

        # Get pending count
        pending_result = await db.execute(text("""
            SELECT COUNT(*) FROM shadow_decisions
            WHERE hypothesis_id = :hid AND outcome = 'PENDING'
        """), {"hid": hypothesis.id})
        pending = pending_result.scalar() or 0

        criteria = hypothesis.entry_criteria or {}
        settled = hypothesis.total_wins + hypothesis.total_losses

        # Format time window
        min_mins = criteria.get("min_minutes_to_start", 0)
        max_mins = criteria.get("max_minutes_to_start", 1440)
        time_window = f"{min_mins//60}h-{max_mins//60}h before kickoff"

        # Calculate ROI
        total_staked = hypothesis.total_decisions * 10 if hypothesis.total_decisions > 0 else 1
        roi = float(hypothesis.total_pnl) / total_staked * 100

        return HypothesisDetail(
            id=hypothesis.id,
            name=hypothesis.name,
            display_name=hypothesis.display_name,
            description=hypothesis.description,
            enabled=hypothesis.enabled,
            selection_logic=hypothesis.selection_logic,
            decision_type=hypothesis.decision_type,
            min_score=criteria.get("min_score", 0),
            min_price_change_pct=criteria.get("min_price_change_pct", 0),
            price_change_direction=criteria.get("price_change_direction"),
            time_window=time_window,
            total_decisions=hypothesis.total_decisions,
            wins=hypothesis.total_wins,
            losses=hypothesis.total_losses,
            pending=pending,
            win_rate=round(hypothesis.total_wins / settled * 100, 1) if settled > 0 else 0.0,
            total_pnl=float(hypothesis.total_pnl),
            avg_clv=float(hypothesis.avg_clv) if hypothesis.avg_clv else None,
            roi_percent=round(roi, 2),
            last_decision_at=hypothesis.last_decision_at.isoformat() if hypothesis.last_decision_at else None,
            created_at=hypothesis.created_at.isoformat(),
            entry_criteria=hypothesis.entry_criteria,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_hypothesis_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{hypothesis_name}/decisions", response_model=list[HypothesisDecision])
async def get_hypothesis_decisions(
    hypothesis_name: str,
    db: AsyncSession = Depends(get_db),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get recent decisions made by a specific hypothesis.
    """
    try:
        # Build query
        where_clauses = ["h.name = :hypothesis_name"]
        params = {"hypothesis_name": hypothesis_name, "limit": limit}

        if outcome:
            where_clauses.append("sd.outcome = :outcome")
            params["outcome"] = outcome

        where_sql = " AND ".join(where_clauses)

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
                sd.price_change_1h,
                sd.price_change_2h,
                sd.closing_back_price,
                sd.closing_lay_price,
                sd.clv_percent,
                sd.outcome,
                sd.net_pnl
            FROM shadow_decisions sd
            JOIN trading_hypotheses h ON sd.hypothesis_id = h.id
            JOIN markets m ON sd.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            JOIN runners r ON sd.runner_id = r.id
            WHERE {where_sql}
            ORDER BY sd.decision_at DESC
            LIMIT :limit
        """)

        result = await db.execute(query, params)
        rows = result.fetchall()

        return [
            HypothesisDecision(
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
                price_change_1h=float(row.price_change_1h) if row.price_change_1h else None,
                price_change_2h=float(row.price_change_2h) if row.price_change_2h else None,
                closing_price=float(
                    row.closing_back_price if row.decision_type == "BACK"
                    else row.closing_lay_price
                ) if row.closing_back_price else None,
                clv_percent=float(row.clv_percent) if row.clv_percent else None,
                outcome=row.outcome or "PENDING",
                net_pnl=float(row.net_pnl) if row.net_pnl else None,
            )
            for row in rows
        ]

    except Exception as e:
        logger.error("get_hypothesis_decisions_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{hypothesis_name}/toggle")
async def toggle_hypothesis(
    hypothesis_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Enable or disable a hypothesis.
    """
    try:
        result = await db.execute(
            select(TradingHypothesis).where(TradingHypothesis.name == hypothesis_name)
        )
        hypothesis = result.scalar_one_or_none()

        if not hypothesis:
            raise HTTPException(status_code=404, detail=f"Hypothesis '{hypothesis_name}' not found")

        hypothesis.enabled = not hypothesis.enabled
        await db.commit()

        logger.info(
            "hypothesis_toggled",
            name=hypothesis_name,
            enabled=hypothesis.enabled,
        )

        return {
            "name": hypothesis_name,
            "enabled": hypothesis.enabled,
            "message": f"Hypothesis {'enabled' if hypothesis.enabled else 'disabled'}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_hypothesis_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed")
async def seed_hypotheses(db: AsyncSession = Depends(get_db)):
    """
    Seed the default trading hypotheses.

    Safe to call multiple times - only creates hypotheses that don't exist.
    """
    try:
        from app.tasks.hypothesis import seed_default_hypotheses
        stats = await seed_default_hypotheses(db)
        return {"status": "success", **stats}
    except Exception as e:
        logger.error("seed_hypotheses_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", status_code=201)
async def create_hypothesis(
    data: HypothesisCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new trading hypothesis.

    The hypothesis will start collecting paper trading decisions immediately
    if enabled and Phase 2 is active.
    """
    try:
        # Check if name already exists
        existing = await db.execute(
            select(TradingHypothesis).where(TradingHypothesis.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Hypothesis '{data.name}' already exists")

        # Build entry criteria dict
        entry_criteria = {
            "min_score": data.min_score,
            "min_price_change_pct": data.min_price_change_pct,
            "min_minutes_to_start": data.min_minutes_to_start,
            "max_minutes_to_start": data.max_minutes_to_start,
            "min_price": data.min_price,
            "max_price": data.max_price,
        }

        if data.price_change_direction:
            entry_criteria["price_change_direction"] = data.price_change_direction

        if data.market_types:
            entry_criteria["market_types"] = data.market_types

        # Create hypothesis
        hypothesis = TradingHypothesis(
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            selection_logic=data.selection_logic,
            decision_type=data.decision_type,
            enabled=data.enabled,
            entry_criteria=entry_criteria,
        )

        db.add(hypothesis)
        await db.commit()
        await db.refresh(hypothesis)

        logger.info(
            "hypothesis_created",
            name=data.name,
            enabled=data.enabled,
        )

        return {
            "status": "created",
            "id": hypothesis.id,
            "name": hypothesis.name,
            "display_name": hypothesis.display_name,
            "enabled": hypothesis.enabled,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_hypothesis_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{hypothesis_name}")
async def update_hypothesis(
    hypothesis_name: str,
    data: HypothesisUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing trading hypothesis.

    Only provided fields will be updated.
    """
    try:
        result = await db.execute(
            select(TradingHypothesis).where(TradingHypothesis.name == hypothesis_name)
        )
        hypothesis = result.scalar_one_or_none()

        if not hypothesis:
            raise HTTPException(status_code=404, detail=f"Hypothesis '{hypothesis_name}' not found")

        # Update basic fields
        if data.display_name is not None:
            hypothesis.display_name = data.display_name
        if data.description is not None:
            hypothesis.description = data.description
        if data.selection_logic is not None:
            hypothesis.selection_logic = data.selection_logic
        if data.decision_type is not None:
            hypothesis.decision_type = data.decision_type
        if data.enabled is not None:
            hypothesis.enabled = data.enabled

        # Update entry criteria
        criteria = hypothesis.entry_criteria or {}

        if data.min_score is not None:
            criteria["min_score"] = data.min_score
        if data.min_price_change_pct is not None:
            criteria["min_price_change_pct"] = data.min_price_change_pct
        if data.price_change_direction is not None:
            criteria["price_change_direction"] = data.price_change_direction
        if data.min_minutes_to_start is not None:
            criteria["min_minutes_to_start"] = data.min_minutes_to_start
        if data.max_minutes_to_start is not None:
            criteria["max_minutes_to_start"] = data.max_minutes_to_start
        if data.market_types is not None:
            criteria["market_types"] = data.market_types
        if data.min_price is not None:
            criteria["min_price"] = data.min_price
        if data.max_price is not None:
            criteria["max_price"] = data.max_price

        hypothesis.entry_criteria = criteria
        await db.commit()

        logger.info(
            "hypothesis_updated",
            name=hypothesis_name,
        )

        return {
            "status": "updated",
            "name": hypothesis_name,
            "enabled": hypothesis.enabled,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_hypothesis_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{hypothesis_name}")
async def delete_hypothesis(
    hypothesis_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a trading hypothesis.

    WARNING: This will also delete all associated shadow decisions.
    Only use for hypotheses with no valuable data.
    """
    try:
        result = await db.execute(
            select(TradingHypothesis).where(TradingHypothesis.name == hypothesis_name)
        )
        hypothesis = result.scalar_one_or_none()

        if not hypothesis:
            raise HTTPException(status_code=404, detail=f"Hypothesis '{hypothesis_name}' not found")

        # Check if it has decisions
        decision_count = await db.execute(text("""
            SELECT COUNT(*) FROM shadow_decisions WHERE hypothesis_id = :hid
        """), {"hid": hypothesis.id})
        count = decision_count.scalar() or 0

        if count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete hypothesis with {count} decisions. Disable it instead."
            )

        await db.delete(hypothesis)
        await db.commit()

        logger.info("hypothesis_deleted", name=hypothesis_name)

        return {"status": "deleted", "name": hypothesis_name}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_hypothesis_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{hypothesis_name}/daily-pnl")
async def get_hypothesis_daily_pnl(
    hypothesis_name: str,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
):
    """
    Get daily P&L for a specific hypothesis.
    """
    try:
        query = text(f"""
            SELECT
                DATE(sd.decision_at) AS date,
                COUNT(*) AS decisions,
                COUNT(*) FILTER (WHERE sd.outcome = 'WIN') AS wins,
                COUNT(*) FILTER (WHERE sd.outcome = 'LOSE') AS losses,
                COALESCE(SUM(sd.net_pnl), 0) AS net_pnl,
                SUM(SUM(sd.net_pnl)) OVER (ORDER BY DATE(sd.decision_at)) AS cumulative_pnl
            FROM shadow_decisions sd
            JOIN trading_hypotheses h ON sd.hypothesis_id = h.id
            WHERE
                h.name = :hypothesis_name
                AND sd.decision_at >= CURRENT_DATE - INTERVAL '{days} days'
                AND sd.outcome IN ('WIN', 'LOSE')
            GROUP BY DATE(sd.decision_at)
            ORDER BY DATE(sd.decision_at)
        """)

        result = await db.execute(query, {"hypothesis_name": hypothesis_name})
        rows = result.fetchall()

        return {
            "hypothesis": hypothesis_name,
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

    except Exception as e:
        logger.error("get_hypothesis_daily_pnl_error", hypothesis=hypothesis_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
