"""Competition API endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.domain import Competition, CompetitionStats

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


class CompetitionRankingItem(BaseModel):
    """Competition ranking item."""

    competition_id: int
    name: str
    country_code: str | None
    total_markets: int
    avg_score: float
    max_score: float
    markets_above_55: int
    markets_above_70: int


@router.get("/rankings", response_model=list[CompetitionRankingItem])
async def get_competition_rankings(
    db: AsyncSession = Depends(get_db),
    min_markets: int = Query(5, ge=1, description="Minimum markets to include"),
    days: int = Query(30, ge=1, le=90, description="Rolling window in days"),
):
    """
    Get competition rankings based on rolling average scores.

    Returns competitions sorted by their average score over the past N days.
    This is LEARNED from actual market data, not pre-configured.

    High-scoring competitions = consistently exploitable markets.
    Low-scoring competitions = efficient markets (EPL, UCL, etc.)
    """
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

    result = await db.execute(query)
    rows = result.all()

    return [
        CompetitionRankingItem(
            competition_id=row.id,
            name=row.name,
            country_code=row.country_code,
            total_markets=row.total_markets or 0,
            avg_score=float(row.avg_score) if row.avg_score else 0,
            max_score=float(row.max_score) if row.max_score else 0,
            markets_above_55=row.markets_above_55 or 0,
            markets_above_70=row.markets_above_70 or 0,
        )
        for row in rows
    ]


@router.get("")
async def list_competitions(
    db: AsyncSession = Depends(get_db),
    enabled_only: bool = Query(True, description="Only show enabled competitions"),
):
    """
    List all competitions.

    Returns basic competition info without score statistics.
    """
    query = select(Competition)
    if enabled_only:
        query = query.where(Competition.enabled == True)
    query = query.order_by(Competition.name)

    result = await db.execute(query)
    competitions = result.scalars().all()

    return {
        "items": [
            {
                "id": c.id,
                "betfair_id": c.betfair_id,
                "name": c.name,
                "country_code": c.country_code,
                "enabled": c.enabled,
                "tier": c.tier,
            }
            for c in competitions
        ],
        "total": len(competitions),
    }


@router.get("/{competition_id}/stats")
async def get_competition_stats(
    competition_id: int,
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
):
    """
    Get detailed statistics for a specific competition.

    Shows daily score trends over the specified period.
    """
    cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days)

    # Get competition info
    comp_result = await db.execute(
        select(Competition).where(Competition.id == competition_id)
    )
    competition = comp_result.scalar_one_or_none()

    if not competition:
        return {"error": "Competition not found"}

    # Get daily stats
    stats_result = await db.execute(
        select(CompetitionStats)
        .where(
            CompetitionStats.competition_id == competition_id,
            CompetitionStats.stats_date >= cutoff_date,
        )
        .order_by(CompetitionStats.stats_date.desc())
    )
    stats = stats_result.scalars().all()

    return {
        "competition": {
            "id": competition.id,
            "name": competition.name,
            "country_code": competition.country_code,
            "enabled": competition.enabled,
        },
        "daily_stats": [
            {
                "date": str(s.stats_date),
                "markets_scored": s.markets_scored,
                "avg_score": float(s.avg_score) if s.avg_score else None,
                "max_score": float(s.max_score) if s.max_score else None,
                "min_score": float(s.min_score) if s.min_score else None,
                "markets_above_55": s.markets_above_55,
                "markets_above_70": s.markets_above_70,
                "rolling_30d_avg": float(s.rolling_30d_avg_score) if s.rolling_30d_avg_score else None,
            }
            for s in stats
        ],
    }
