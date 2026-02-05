"""Momentum API Endpoints.

Provides endpoints for tracking steamers (prices shortening) and
drifters (prices lengthening) across active markets.
"""

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.services.momentum import MomentumAnalyzer

router = APIRouter(prefix="/api/momentum", tags=["momentum"])
logger = structlog.get_logger(__name__)


# =============================================================================
# Response Models
# =============================================================================

class RunnerMovement(BaseModel):
    """Price movement data for a runner."""

    runner_id: int
    runner_name: str
    market_id: int
    event_name: str
    competition_name: str
    market_type: str
    minutes_to_start: int

    current_back: float
    current_lay: float

    change_30m: Optional[float]
    change_1h: Optional[float]
    change_2h: Optional[float]
    change_4h: Optional[float]

    movement_type: str  # STEAMER, DRIFTER, STABLE
    movement_strength: str  # SHARP, MODERATE, SLIGHT

    total_matched: float
    matched_change_1h: Optional[float]


class MomentumResponse(BaseModel):
    """Response containing market movers."""

    steamers: list[RunnerMovement]
    drifters: list[RunnerMovement]
    sharp_moves: list[RunnerMovement]
    total_markets_analyzed: int
    timestamp: str
    disclaimer: str


class MoverStats(BaseModel):
    """Statistics about current movers."""

    total_steamers: int
    total_drifters: int
    sharp_steamers: int
    sharp_drifters: int
    avg_steamer_change: float
    avg_drifter_change: float
    markets_with_movement: int
    total_markets: int


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/movers", response_model=MomentumResponse)
async def get_movers(
    db: AsyncSession = Depends(get_db),
    min_change: float = Query(3.0, ge=1.0, le=20.0, description="Minimum % change"),
    hours_ahead: int = Query(24, ge=1, le=72, description="Hours ahead to look"),
    limit: int = Query(30, ge=1, le=100, description="Max results per category"),
):
    """
    Get current steamers and drifters across all active markets.

    - **Steamers**: Prices shortening (getting shorter odds)
    - **Drifters**: Prices lengthening (getting longer odds)
    - **Sharp moves**: Significant price changes (>10%)

    Useful for identifying smart money movements and market sentiment shifts.
    """
    try:
        analyzer = MomentumAnalyzer(db)
        summary = await analyzer.get_current_movers(
            min_change_pct=min_change,
            hours_ahead=hours_ahead,
            limit=limit,
        )

        return MomentumResponse(
            steamers=[
                RunnerMovement(
                    runner_id=r.runner_id,
                    runner_name=r.runner_name,
                    market_id=r.market_id,
                    event_name=r.event_name,
                    competition_name=r.competition_name,
                    market_type=r.market_type,
                    minutes_to_start=r.minutes_to_start,
                    current_back=r.current_back,
                    current_lay=r.current_lay,
                    change_30m=round(r.change_30m * 100, 2) if r.change_30m else None,
                    change_1h=round(r.change_1h * 100, 2) if r.change_1h else None,
                    change_2h=round(r.change_2h * 100, 2) if r.change_2h else None,
                    change_4h=round(r.change_4h * 100, 2) if r.change_4h else None,
                    movement_type=r.movement_type,
                    movement_strength=r.movement_strength,
                    total_matched=r.total_matched,
                    matched_change_1h=r.matched_change_1h,
                )
                for r in summary.steamers
            ],
            drifters=[
                RunnerMovement(
                    runner_id=r.runner_id,
                    runner_name=r.runner_name,
                    market_id=r.market_id,
                    event_name=r.event_name,
                    competition_name=r.competition_name,
                    market_type=r.market_type,
                    minutes_to_start=r.minutes_to_start,
                    current_back=r.current_back,
                    current_lay=r.current_lay,
                    change_30m=round(r.change_30m * 100, 2) if r.change_30m else None,
                    change_1h=round(r.change_1h * 100, 2) if r.change_1h else None,
                    change_2h=round(r.change_2h * 100, 2) if r.change_2h else None,
                    change_4h=round(r.change_4h * 100, 2) if r.change_4h else None,
                    movement_type=r.movement_type,
                    movement_strength=r.movement_strength,
                    total_matched=r.total_matched,
                    matched_change_1h=r.matched_change_1h,
                )
                for r in summary.drifters
            ],
            sharp_moves=[
                RunnerMovement(
                    runner_id=r.runner_id,
                    runner_name=r.runner_name,
                    market_id=r.market_id,
                    event_name=r.event_name,
                    competition_name=r.competition_name,
                    market_type=r.market_type,
                    minutes_to_start=r.minutes_to_start,
                    current_back=r.current_back,
                    current_lay=r.current_lay,
                    change_30m=round(r.change_30m * 100, 2) if r.change_30m else None,
                    change_1h=round(r.change_1h * 100, 2) if r.change_1h else None,
                    change_2h=round(r.change_2h * 100, 2) if r.change_2h else None,
                    change_4h=round(r.change_4h * 100, 2) if r.change_4h else None,
                    movement_type=r.movement_type,
                    movement_strength=r.movement_strength,
                    total_matched=r.total_matched,
                    matched_change_1h=r.matched_change_1h,
                )
                for r in summary.sharp_moves
            ],
            total_markets_analyzed=summary.total_markets_analyzed,
            timestamp=summary.timestamp.isoformat(),
            disclaimer="Price movements are informational only. Past movements do not predict future results.",
        )

    except Exception as e:
        logger.error("momentum_movers_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Failed to get movers: {str(e)}")


@router.get("/stats", response_model=MoverStats)
async def get_mover_stats(
    db: AsyncSession = Depends(get_db),
    hours_ahead: int = Query(24, ge=1, le=72),
):
    """
    Get summary statistics about current market movers.

    Quick overview of market activity and sentiment.
    """
    try:
        analyzer = MomentumAnalyzer(db)

        # Get all movers with low threshold to count everything
        summary = await analyzer.get_current_movers(
            min_change_pct=2.0,  # Low threshold to capture more
            hours_ahead=hours_ahead,
            limit=500,  # Get all
        )

        sharp_steamers = len([s for s in summary.steamers if s.movement_strength == "SHARP"])
        sharp_drifters = len([d for d in summary.drifters if d.movement_strength == "SHARP"])

        avg_steamer = 0.0
        if summary.steamers:
            changes = [s.change_2h or s.change_1h or s.change_30m or 0 for s in summary.steamers]
            avg_steamer = sum(changes) / len(changes) * 100

        avg_drifter = 0.0
        if summary.drifters:
            changes = [d.change_2h or d.change_1h or d.change_30m or 0 for d in summary.drifters]
            avg_drifter = sum(changes) / len(changes) * 100

        # Markets with any significant movement
        mover_market_ids = set(
            [s.market_id for s in summary.steamers] +
            [d.market_id for d in summary.drifters]
        )

        return MoverStats(
            total_steamers=len(summary.steamers),
            total_drifters=len(summary.drifters),
            sharp_steamers=sharp_steamers,
            sharp_drifters=sharp_drifters,
            avg_steamer_change=round(avg_steamer, 2),
            avg_drifter_change=round(avg_drifter, 2),
            markets_with_movement=len(mover_market_ids),
            total_markets=summary.total_markets_analyzed,
        )

    except Exception as e:
        logger.error("momentum_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/steamers", response_model=list[RunnerMovement])
async def get_steamers(
    db: AsyncSession = Depends(get_db),
    min_change: float = Query(3.0, ge=1.0, le=20.0),
    hours_ahead: int = Query(24, ge=1, le=72),
    limit: int = Query(20, ge=1, le=100),
):
    """Get only steamers (prices shortening)."""
    try:
        analyzer = MomentumAnalyzer(db)
        summary = await analyzer.get_current_movers(
            min_change_pct=min_change,
            hours_ahead=hours_ahead,
            limit=limit,
        )

        return [
            RunnerMovement(
                runner_id=r.runner_id,
                runner_name=r.runner_name,
                market_id=r.market_id,
                event_name=r.event_name,
                competition_name=r.competition_name,
                market_type=r.market_type,
                minutes_to_start=r.minutes_to_start,
                current_back=r.current_back,
                current_lay=r.current_lay,
                change_30m=round(r.change_30m * 100, 2) if r.change_30m else None,
                change_1h=round(r.change_1h * 100, 2) if r.change_1h else None,
                change_2h=round(r.change_2h * 100, 2) if r.change_2h else None,
                change_4h=round(r.change_4h * 100, 2) if r.change_4h else None,
                movement_type=r.movement_type,
                movement_strength=r.movement_strength,
                total_matched=r.total_matched,
                matched_change_1h=r.matched_change_1h,
            )
            for r in summary.steamers
        ]

    except Exception as e:
        logger.error("steamers_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get steamers: {str(e)}")


@router.get("/diagnostics")
async def get_momentum_diagnostics(
    db: AsyncSession = Depends(get_db),
    hours_ahead: int = Query(24, ge=1, le=72),
):
    """
    Diagnostic endpoint showing data availability for momentum analysis.

    Helps understand why there might be 0 movers detected.
    """
    from sqlalchemy import text
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)

    # Pre-compute all time boundaries to avoid asyncpg type issues
    t_30m = now - timedelta(minutes=30)
    t_1h = now - timedelta(hours=1)
    t_2h = now - timedelta(hours=2)
    t_4h = now - timedelta(hours=4)
    t_5h = now - timedelta(hours=5)
    t_90m = now - timedelta(minutes=90)

    try:
        # Check snapshot distribution
        result = await db.execute(text("""
            SELECT
                CASE
                    WHEN captured_at > :t_30m THEN 'a_last_30m'
                    WHEN captured_at > :t_1h THEN 'b_30m_to_1h'
                    WHEN captured_at > :t_2h THEN 'c_1h_to_2h'
                    WHEN captured_at > :t_4h THEN 'd_2h_to_4h'
                    ELSE 'e_older'
                END as time_bucket,
                COUNT(DISTINCT market_id) as unique_markets,
                COUNT(*) as total_snapshots
            FROM market_snapshots
            WHERE captured_at > :t_5h
            GROUP BY 1
            ORDER BY 1
        """), {"t_30m": t_30m, "t_1h": t_1h, "t_2h": t_2h, "t_4h": t_4h, "t_5h": t_5h})

        snapshot_distribution = {row[0]: {"markets": row[1], "snapshots": row[2]} for row in result}

        # Check markets with comparable data (both current AND historical)
        result2 = await db.execute(text("""
            WITH current_markets AS (
                SELECT DISTINCT market_id
                FROM market_snapshots
                WHERE captured_at > :t_30m
            ),
            historical_markets AS (
                SELECT DISTINCT market_id
                FROM market_snapshots
                WHERE captured_at BETWEEN :t_90m AND :t_30m
            )
            SELECT
                (SELECT COUNT(*) FROM current_markets) as markets_with_current,
                (SELECT COUNT(*) FROM historical_markets) as markets_with_historical,
                (SELECT COUNT(*) FROM current_markets c
                 JOIN historical_markets h ON c.market_id = h.market_id) as markets_with_both
        """), {"t_30m": t_30m, "t_90m": t_90m})

        row = result2.fetchone()

        # Check active markets in time window
        result3 = await db.execute(text("""
            SELECT COUNT(*)
            FROM markets m
            JOIN events e ON m.event_id = e.id
            WHERE e.scheduled_start > :now
              AND e.scheduled_start < :cutoff
              AND m.status = 'OPEN'
        """), {"now": now, "cutoff": cutoff})

        active_markets = result3.scalar()

        # Check enabled competitions and their market counts
        result4 = await db.execute(text("""
            SELECT
                c.enabled,
                COUNT(DISTINCT c.id) as competition_count,
                COUNT(DISTINCT m.id) as market_count
            FROM competitions c
            LEFT JOIN events e ON e.competition_id = c.id
            LEFT JOIN markets m ON m.event_id = e.id AND m.status = 'OPEN' AND m.in_play = FALSE
            GROUP BY c.enabled
        """))

        competition_stats = {}
        for row4 in result4:
            key = "enabled" if row4[0] else "disabled"
            competition_stats[key] = {
                "competitions": row4[1],
                "open_markets": row4[2] or 0
            }

        # Get recent job runs with full metadata
        # Note: The model uses job_metadata as Python attr, but DB column is "metadata"
        result5 = await db.execute(text("""
            SELECT
                job_name,
                status,
                records_processed,
                started_at,
                completed_at,
                error_message,
                metadata
            FROM job_runs
            WHERE job_name = 'capture_snapshots'
            ORDER BY started_at DESC
            LIMIT 5
        """))

        recent_jobs = []
        for job_row in result5:
            recent_jobs.append({
                "job_name": job_row[0],
                "status": job_row[1],
                "records_processed": job_row[2],
                "started_at": job_row[3].isoformat() if job_row[3] else None,
                "completed_at": job_row[4].isoformat() if job_row[4] else None,
                "error_message": job_row[5],
                "job_metadata": job_row[6],  # This contains markets_queried, errors, etc.
            })

        # Check how many markets would be captured (same criteria as snapshot task)
        result6 = await db.execute(text("""
            SELECT COUNT(*)
            FROM markets m
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            WHERE m.status = 'OPEN'
              AND m.in_play = FALSE
              AND c.enabled = TRUE
        """))

        capturable_markets = result6.scalar()

        return {
            "timestamp": now.isoformat(),
            "hours_ahead": hours_ahead,
            "active_markets_in_window": active_markets,
            "capturable_markets_for_snapshots": capturable_markets,
            "markets_with_current_snapshot": row[0] if row else 0,
            "markets_with_historical_snapshot": row[1] if row else 0,
            "markets_with_both_for_comparison": row[2] if row else 0,
            "snapshot_distribution": snapshot_distribution,
            "competition_stats": competition_stats,
            "recent_snapshot_jobs": recent_jobs,
            "explanation": {
                "a_last_30m": "Snapshots from the last 30 minutes (current prices)",
                "b_30m_to_1h": "Snapshots from 30-60 mins ago (for 30m comparison)",
                "c_1h_to_2h": "Snapshots from 1-2 hours ago (for 1h/2h comparison)",
                "d_2h_to_4h": "Snapshots from 2-4 hours ago (for 4h comparison)",
                "e_older": "Older snapshots (not used for momentum)",
            },
            "note": "For momentum detection, markets need snapshots from both current AND historical timeframes. Check recent_snapshot_jobs for job_metadata to see why only some markets are captured."
        }

    except Exception as e:
        logger.error("momentum_diagnostics_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get diagnostics: {str(e)}")


@router.get("/drifters", response_model=list[RunnerMovement])
async def get_drifters(
    db: AsyncSession = Depends(get_db),
    min_change: float = Query(3.0, ge=1.0, le=20.0),
    hours_ahead: int = Query(24, ge=1, le=72),
    limit: int = Query(20, ge=1, le=100),
):
    """Get only drifters (prices lengthening)."""
    try:
        analyzer = MomentumAnalyzer(db)
        summary = await analyzer.get_current_movers(
            min_change_pct=min_change,
            hours_ahead=hours_ahead,
            limit=limit,
        )

        return [
            RunnerMovement(
                runner_id=r.runner_id,
                runner_name=r.runner_name,
                market_id=r.market_id,
                event_name=r.event_name,
                competition_name=r.competition_name,
                market_type=r.market_type,
                minutes_to_start=r.minutes_to_start,
                current_back=r.current_back,
                current_lay=r.current_lay,
                change_30m=round(r.change_30m * 100, 2) if r.change_30m else None,
                change_1h=round(r.change_1h * 100, 2) if r.change_1h else None,
                change_2h=round(r.change_2h * 100, 2) if r.change_2h else None,
                change_4h=round(r.change_4h * 100, 2) if r.change_4h else None,
                movement_type=r.movement_type,
                movement_strength=r.movement_strength,
                total_matched=r.total_matched,
                matched_change_1h=r.matched_change_1h,
            )
            for r in summary.drifters
        ]

    except Exception as e:
        logger.error("drifters_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get drifters: {str(e)}")
