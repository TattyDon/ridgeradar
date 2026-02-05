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
