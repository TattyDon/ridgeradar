"""Market API endpoints."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_db
from app.models.domain import (
    Competition,
    Event,
    Market,
    MarketProfileDaily,
    MarketSnapshot,
    Runner,
)

router = APIRouter(prefix="/api/markets", tags=["markets"])


class RunnerResponse(BaseModel):
    """Runner in API response."""

    id: int
    betfair_id: int
    name: str
    status: str

    class Config:
        from_attributes = True


class MarketListItem(BaseModel):
    """Market item in list response."""

    id: int
    betfair_id: str
    name: str
    market_type: str
    total_matched: float
    status: str
    in_play: bool
    event_name: str
    competition_name: str
    scheduled_start: datetime

    class Config:
        from_attributes = True


class MarketDetail(BaseModel):
    """Detailed market response."""

    id: int
    betfair_id: str
    name: str
    market_type: str
    total_matched: float
    status: str
    in_play: bool
    event_name: str
    competition_name: str
    scheduled_start: datetime
    runners: list[RunnerResponse]
    snapshot_count: int
    latest_snapshot: dict | None = None

    class Config:
        from_attributes = True


class MarketListResponse(BaseModel):
    """Paginated market list response."""

    items: list[MarketListItem]
    total: int
    page: int
    page_size: int


@router.get("", response_model=MarketListResponse)
async def list_markets(
    db: AsyncSession = Depends(get_db),
    competition_id: int | None = Query(None, description="Filter by competition ID"),
    status: str = Query("OPEN", description="Market status filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """
    List markets with optional filtering.

    Only returns markets from enabled competitions.
    """
    # Base query with joins
    query = (
        select(Market)
        .join(Event)
        .join(Competition)
        .where(Competition.enabled == True)
    )

    # Apply filters
    if competition_id:
        query = query.where(Competition.id == competition_id)
    if status:
        query = query.where(Market.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = (
        query.options(
            joinedload(Market.event).joinedload(Event.competition)
        )
        .order_by(Event.scheduled_start)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    markets = result.unique().scalars().all()

    items = [
        MarketListItem(
            id=m.id,
            betfair_id=m.betfair_id,
            name=m.name,
            market_type=m.market_type,
            total_matched=float(m.total_matched or 0),
            status=m.status,
            in_play=m.in_play,
            event_name=m.event.name,
            competition_name=m.event.competition.name,
            scheduled_start=m.event.scheduled_start,
        )
        for m in markets
    ]

    return MarketListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{market_id}", response_model=MarketDetail)
async def get_market(
    market_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get market detail with latest snapshot.

    Returns 404 for disabled competition markets.
    """
    # Get market with related data
    result = await db.execute(
        select(Market)
        .options(
            joinedload(Market.event).joinedload(Event.competition),
            joinedload(Market.runners),
        )
        .where(Market.id == market_id)
    )
    market = result.unique().scalar_one_or_none()

    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    # Check if competition is disabled
    if not market.event.competition.enabled:
        raise HTTPException(status_code=404, detail="Market not found")

    # Get snapshot count
    count_result = await db.execute(
        select(func.count())
        .select_from(MarketSnapshot)
        .where(MarketSnapshot.market_id == market_id)
    )
    snapshot_count = count_result.scalar() or 0

    # Get latest snapshot
    latest_result = await db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.market_id == market_id)
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(1)
    )
    latest_snapshot = latest_result.scalar_one_or_none()

    return MarketDetail(
        id=market.id,
        betfair_id=market.betfair_id,
        name=market.name,
        market_type=market.market_type,
        total_matched=float(market.total_matched or 0),
        status=market.status,
        in_play=market.in_play,
        event_name=market.event.name,
        competition_name=market.event.competition.name,
        scheduled_start=market.event.scheduled_start,
        runners=[
            RunnerResponse(
                id=r.id,
                betfair_id=r.betfair_id,
                name=r.name,
                status=r.status,
            )
            for r in market.runners
        ],
        snapshot_count=snapshot_count,
        latest_snapshot=latest_snapshot.ladder_data if latest_snapshot else None,
    )


@router.get("/{market_id}/snapshots")
async def get_market_snapshots(
    market_id: int,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
):
    """Get recent snapshots for a market."""
    # Verify market exists and competition is enabled
    result = await db.execute(
        select(Market)
        .join(Event)
        .join(Competition)
        .where(Market.id == market_id, Competition.enabled == True)
    )
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    # Get snapshots
    result = await db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.market_id == market_id)
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(limit)
    )
    snapshots = result.scalars().all()

    return {
        "market_id": market_id,
        "count": len(snapshots),
        "snapshots": [
            {
                "id": s.id,
                "captured_at": s.captured_at,
                "total_matched": float(s.total_matched or 0),
                "total_available": float(s.total_available or 0),
                "overround": float(s.overround or 0),
                "ladder_data": s.ladder_data,
            }
            for s in snapshots
        ],
    }


@router.get("/{market_id}/profiles")
async def get_market_profiles(
    market_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get profiles for a market."""
    # Verify market exists and competition is enabled
    result = await db.execute(
        select(Market)
        .join(Event)
        .join(Competition)
        .where(Market.id == market_id, Competition.enabled == True)
    )
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    # Get profiles
    result = await db.execute(
        select(MarketProfileDaily)
        .where(MarketProfileDaily.market_id == market_id)
        .order_by(MarketProfileDaily.profile_date.desc(), MarketProfileDaily.time_bucket)
    )
    profiles = result.scalars().all()

    return {
        "market_id": market_id,
        "profiles": [
            {
                "profile_date": str(p.profile_date),
                "time_bucket": p.time_bucket,
                "avg_spread_ticks": float(p.avg_spread_ticks or 0),
                "spread_volatility": float(p.spread_volatility or 0),
                "avg_depth_best": float(p.avg_depth_best or 0),
                "depth_5_ticks": float(p.depth_5_ticks or 0),
                "total_matched_volume": float(p.total_matched_volume or 0),
                "update_rate_per_min": float(p.update_rate_per_min or 0),
                "price_volatility": float(p.price_volatility or 0),
                "mean_price": float(p.mean_price or 0),
                "snapshot_count": p.snapshot_count,
            }
            for p in profiles
        ],
    }
