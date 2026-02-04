"""Exploitability scores API endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_db
from app.models.domain import Competition, Event, ExploitabilityScore, Market

router = APIRouter(prefix="/api/scores", tags=["scores"])


class ScoreListItem(BaseModel):
    """Score item in list response."""

    id: int
    market_id: int
    market_name: str
    event_name: str
    competition_name: str
    scored_at: datetime
    time_bucket: str
    odds_band: str
    spread_score: float
    volatility_score: float
    update_score: float
    depth_score: float
    volume_penalty: float
    total_score: float

    class Config:
        from_attributes = True


class ScoreListResponse(BaseModel):
    """Score list response."""

    items: list[ScoreListItem]
    total: int


@router.get("", response_model=ScoreListResponse)
async def list_scores(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(50, description="Minimum total score"),
    time_bucket: str | None = Query(None, description="Filter by time bucket"),
    odds_band: str | None = Query(None, description="Filter by odds band"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    List exploitability scores.

    Scores are filtered by the scoring engine's volume penalty -
    high volume (efficient) markets automatically score lower.
    """
    query = (
        select(ExploitabilityScore, Market, Event, Competition)
        .join(Market, ExploitabilityScore.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(Competition, Event.competition_id == Competition.id)
        .where(
            Competition.enabled == True,
            ExploitabilityScore.total_score >= min_score,
        )
    )

    # Apply filters
    if time_bucket:
        query = query.where(ExploitabilityScore.time_bucket == time_bucket)
    if odds_band:
        query = query.where(ExploitabilityScore.odds_band == odds_band)

    # Order by score and apply limit
    query = query.order_by(ExploitabilityScore.total_score.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    items = [
        ScoreListItem(
            id=score.id,
            market_id=market.id,
            market_name=market.name,
            event_name=event.name,
            competition_name=competition.name,
            scored_at=score.scored_at,
            time_bucket=score.time_bucket,
            odds_band=score.odds_band,
            spread_score=float(score.spread_score or 0),
            volatility_score=float(score.volatility_score or 0),
            update_score=float(score.update_score or 0),
            depth_score=float(score.depth_score or 0),
            volume_penalty=float(score.volume_penalty or 0),
            total_score=float(score.total_score),
        )
        for score, market, event, competition in rows
    ]

    return ScoreListResponse(items=items, total=len(items))


@router.get("/top")
async def top_scores(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Get top N markets by score.

    Returns the highest scoring markets for quick dashboard view.
    High volume (efficient) markets automatically score lower.
    """
    query = (
        select(ExploitabilityScore, Market, Event, Competition)
        .join(Market, ExploitabilityScore.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(Competition, Event.competition_id == Competition.id)
        .where(
            Competition.enabled == True,
            Market.status == "OPEN",
        )
        .order_by(ExploitabilityScore.total_score.desc())
        .limit(limit)
    )

    result = await db.execute(query)
    rows = result.all()

    return {
        "items": [
            {
                "market_id": market.id,
                "market_name": market.name,
                "event_name": event.name,
                "competition_name": competition.name,
                "score": float(score.total_score),
                "time_bucket": score.time_bucket,
                "scheduled_start": event.scheduled_start,
            }
            for score, market, event, competition in rows
        ]
    }


@router.get("/stats")
async def score_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate statistics about scores."""
    # Total count
    total_query = (
        select(func.count(ExploitabilityScore.id))
        .join(Market, ExploitabilityScore.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(Competition, Event.competition_id == Competition.id)
        .where(Competition.enabled == True)
    )
    total_result = await db.execute(total_query)
    total_count = total_result.scalar() or 0

    # Score distribution
    dist_query = (
        select(
            func.count(ExploitabilityScore.id).filter(
                ExploitabilityScore.total_score >= 70
            ).label("high"),
            func.count(ExploitabilityScore.id).filter(
                ExploitabilityScore.total_score >= 50,
                ExploitabilityScore.total_score < 70,
            ).label("medium"),
            func.count(ExploitabilityScore.id).filter(
                ExploitabilityScore.total_score < 50
            ).label("low"),
        )
        .join(Market, ExploitabilityScore.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(Competition, Event.competition_id == Competition.id)
        .where(Competition.enabled == True)
    )
    dist_result = await db.execute(dist_query)
    dist = dist_result.one()

    # Average by time bucket
    bucket_query = (
        select(
            ExploitabilityScore.time_bucket,
            func.avg(ExploitabilityScore.total_score).label("avg_score"),
            func.count(ExploitabilityScore.id).label("count"),
        )
        .join(Market, ExploitabilityScore.market_id == Market.id)
        .join(Event, Market.event_id == Event.id)
        .join(Competition, Event.competition_id == Competition.id)
        .where(Competition.enabled == True)
        .group_by(ExploitabilityScore.time_bucket)
    )
    bucket_result = await db.execute(bucket_query)
    bucket_stats = [
        {"bucket": row.time_bucket, "avg_score": float(row.avg_score or 0), "count": row.count}
        for row in bucket_result.all()
    ]

    return {
        "total_scores": total_count,
        "distribution": {
            "high_70_plus": dist.high or 0,
            "medium_50_70": dist.medium or 0,
            "low_under_50": dist.low or 0,
        },
        "by_time_bucket": bucket_stats,
    }
