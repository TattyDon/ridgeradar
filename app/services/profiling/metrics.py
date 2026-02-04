"""Market profiling service.

Aggregates snapshots into daily profiles by time bucket for scoring.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean, stdev
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.domain import (
    Competition,
    Event,
    Market,
    MarketProfileDaily,
    MarketSnapshot,
)
from app.services.ingestion.snapshots import extract_snapshot_metrics

logger = structlog.get_logger(__name__)


def get_time_bucket(event_start: datetime, snapshot_time: datetime) -> str:
    """
    Determine time bucket based on time to event start.

    Buckets:
    - '72h+': More than 72 hours before
    - '24-72h': 24 to 72 hours before
    - '6-24h': 6 to 24 hours before
    - '2-6h': 2 to 6 hours before
    - '<2h': Less than 2 hours before
    """
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    if snapshot_time.tzinfo is None:
        snapshot_time = snapshot_time.replace(tzinfo=timezone.utc)

    delta = event_start - snapshot_time
    hours = delta.total_seconds() / 3600

    if hours < 0:
        return "inplay"  # Event has started
    elif hours < 2:
        return "<2h"
    elif hours < 6:
        return "2-6h"
    elif hours < 24:
        return "6-24h"
    elif hours < 72:
        return "24-72h"
    else:
        return "72h+"


def get_odds_band(price: float) -> str:
    """
    Determine odds band from price.

    Bands:
    - 'Heavy Fav': 1.01 - 1.50
    - 'Favourite': 1.50 - 2.00
    - 'Even': 2.00 - 3.00
    - 'Underdog': 3.00 - 5.00
    - 'Longshot': 5.00+
    """
    if price < 1.01:
        return "Unknown"
    elif price <= 1.50:
        return "Heavy Fav"
    elif price <= 2.00:
        return "Favourite"
    elif price <= 3.00:
        return "Even"
    elif price <= 5.00:
        return "Underdog"
    else:
        return "Longshot"


class ProfilingService:
    """
    Service for computing market profiles from snapshots.

    Aggregates snapshot data into daily profiles by time bucket,
    computing key metrics for the scoring engine.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize profiling service.

        Args:
            session: Database session
        """
        self.session = session

    async def compute_profiles_for_date(self, profile_date: date) -> dict[str, int]:
        """
        Compute profiles for all markets with snapshots on a given date.

        Args:
            profile_date: Date to compute profiles for

        Returns:
            Stats dict with counts
        """
        stats = {"markets_processed": 0, "profiles_created": 0}

        # Get all markets with snapshots on this date
        start_of_day = datetime.combine(profile_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        end_of_day = start_of_day + timedelta(days=1)

        result = await self.session.execute(
            select(Market.id)
            .distinct()
            .join(MarketSnapshot)
            .where(
                MarketSnapshot.captured_at >= start_of_day,
                MarketSnapshot.captured_at < end_of_day,
            )
        )
        market_ids = [row[0] for row in result.all()]

        for market_id in market_ids:
            profiles = await self.compute_market_profile(market_id, profile_date)
            stats["markets_processed"] += 1
            stats["profiles_created"] += profiles

        logger.info("profiles_computed", date=str(profile_date), **stats)
        return stats

    async def compute_market_profile(self, market_id: int, profile_date: date) -> int:
        """
        Compute profiles for a single market on a date.

        Returns number of profiles created (one per time bucket).
        """
        # Get market with event info (eager load to avoid lazy loading issues)
        result = await self.session.execute(
            select(Market)
            .options(joinedload(Market.event))
            .where(Market.id == market_id)
        )
        market = result.scalar_one_or_none()
        if not market:
            return 0

        event_start = market.event.scheduled_start

        # Get snapshots for this market on this date
        start_of_day = datetime.combine(profile_date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        end_of_day = start_of_day + timedelta(days=1)

        result = await self.session.execute(
            select(MarketSnapshot)
            .where(
                MarketSnapshot.market_id == market_id,
                MarketSnapshot.captured_at >= start_of_day,
                MarketSnapshot.captured_at < end_of_day,
            )
            .order_by(MarketSnapshot.captured_at)
        )
        snapshots = list(result.scalars().all())

        if not snapshots:
            return 0

        # Group snapshots by time bucket
        buckets: dict[str, list[MarketSnapshot]] = {}
        for snapshot in snapshots:
            bucket = get_time_bucket(event_start, snapshot.captured_at)
            if bucket == "inplay":
                continue  # Skip in-play snapshots
            if bucket not in buckets:
                buckets[bucket] = []
            buckets[bucket].append(snapshot)

        # Compute and store profile for each bucket
        profiles_created = 0
        for bucket, bucket_snapshots in buckets.items():
            profile = self._compute_bucket_profile(bucket_snapshots, market, bucket)
            if profile:
                await self._upsert_profile(market_id, profile_date, bucket, profile)
                profiles_created += 1

        await self.session.commit()
        return profiles_created

    def _compute_bucket_profile(
        self,
        snapshots: list[MarketSnapshot],
        market: Market,
        bucket: str,
    ) -> dict[str, Any] | None:
        """Compute metrics for a bucket of snapshots."""
        if len(snapshots) < 2:
            return None

        # Extract metrics from each snapshot
        metrics_list = [extract_snapshot_metrics(s) for s in snapshots]

        spreads = [m["spread_ticks"] for m in metrics_list if m["spread_ticks"] > 0]
        depths = [m["best_depth"] for m in metrics_list if m["best_depth"] > 0]
        depths_5 = [m["depth_5_ticks"] for m in metrics_list if m["depth_5_ticks"] > 0]
        mid_prices = [m["mid_price"] for m in metrics_list if m["mid_price"] > 0]

        if not spreads or not depths:
            return None

        # Calculate duration for update rate
        first_time = snapshots[0].captured_at
        last_time = snapshots[-1].captured_at
        duration_minutes = (last_time - first_time).total_seconds() / 60
        if duration_minutes <= 0:
            duration_minutes = 1

        # Aggregate metrics
        avg_spread = mean(spreads) if spreads else 0
        spread_vol = stdev(spreads) if len(spreads) > 1 else 0
        avg_depth = mean(depths) if depths else 0
        avg_depth_5 = mean(depths_5) if depths_5 else 0
        avg_mid = mean(mid_prices) if mid_prices else 0

        # Price volatility = std(mid_prices) / mean(mid_prices)
        price_vol = 0
        if len(mid_prices) > 1 and avg_mid > 0:
            price_vol = stdev(mid_prices) / avg_mid

        # Volume is max total_matched
        volumes = [float(s.total_matched or 0) for s in snapshots]
        max_volume = max(volumes) if volumes else 0

        # Update rate
        update_rate = len(snapshots) / duration_minutes

        return {
            "avg_spread_ticks": round(avg_spread, 4),
            "spread_volatility": round(spread_vol, 4),
            "avg_depth_best": round(avg_depth, 2),
            "depth_5_ticks": round(avg_depth_5, 2),
            "total_matched_volume": round(max_volume, 2),
            "update_rate_per_min": round(update_rate, 4),
            "price_volatility": round(price_vol, 6),
            "mean_price": round(avg_mid, 4),
            "snapshot_count": len(snapshots),
        }

    async def _upsert_profile(
        self,
        market_id: int,
        profile_date: date,
        time_bucket: str,
        profile: dict[str, Any],
    ) -> None:
        """Upsert a market profile."""
        stmt = insert(MarketProfileDaily).values(
            market_id=market_id,
            profile_date=profile_date,
            time_bucket=time_bucket,
            avg_spread_ticks=Decimal(str(profile["avg_spread_ticks"])),
            spread_volatility=Decimal(str(profile["spread_volatility"])),
            avg_depth_best=Decimal(str(profile["avg_depth_best"])),
            depth_5_ticks=Decimal(str(profile["depth_5_ticks"])),
            total_matched_volume=Decimal(str(profile["total_matched_volume"])),
            update_rate_per_min=Decimal(str(profile["update_rate_per_min"])),
            price_volatility=Decimal(str(profile["price_volatility"])),
            mean_price=Decimal(str(profile["mean_price"])),
            snapshot_count=profile["snapshot_count"],
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_profile_market_date_bucket",
            set_={
                "avg_spread_ticks": Decimal(str(profile["avg_spread_ticks"])),
                "spread_volatility": Decimal(str(profile["spread_volatility"])),
                "avg_depth_best": Decimal(str(profile["avg_depth_best"])),
                "depth_5_ticks": Decimal(str(profile["depth_5_ticks"])),
                "total_matched_volume": Decimal(str(profile["total_matched_volume"])),
                "update_rate_per_min": Decimal(str(profile["update_rate_per_min"])),
                "price_volatility": Decimal(str(profile["price_volatility"])),
                "mean_price": Decimal(str(profile["mean_price"])),
                "snapshot_count": profile["snapshot_count"],
            },
        )
        await self.session.execute(stmt)

    async def get_latest_profile(
        self, market_id: int
    ) -> MarketProfileDaily | None:
        """Get the most recent profile for a market."""
        result = await self.session.execute(
            select(MarketProfileDaily)
            .where(MarketProfileDaily.market_id == market_id)
            .order_by(MarketProfileDaily.profile_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
