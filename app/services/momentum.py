"""Price momentum analysis service.

Detects steamers (prices shortening) and drifters (prices lengthening)
by analyzing price movements over time from market snapshots.

Key concepts:
- Steamer: Price is getting shorter (lower odds = more likely to win in market's view)
- Drifter: Price is getting longer (higher odds = less likely to win)
- Sharp move: Significant price change in short time (potential smart money)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class RunnerMomentum:
    """Price momentum data for a single runner."""

    runner_id: int
    runner_name: str
    market_id: int
    event_name: str
    competition_name: str
    market_type: str
    event_start: datetime
    minutes_to_start: int

    # Current prices
    current_back: float
    current_lay: float
    current_last_traded: Optional[float]

    # Price changes (negative = steaming, positive = drifting)
    change_30m: Optional[float]  # % change vs 30 mins ago
    change_1h: Optional[float]   # % change vs 1 hour ago
    change_2h: Optional[float]   # % change vs 2 hours ago
    change_4h: Optional[float]   # % change vs 4 hours ago

    # Classification
    movement_type: str  # "STEAMER", "DRIFTER", "STABLE"
    movement_strength: str  # "SHARP", "MODERATE", "SLIGHT"

    # Volume context
    total_matched: float
    matched_change_1h: Optional[float]  # Volume increase in last hour


@dataclass
class MomentumSummary:
    """Summary of market movers."""

    steamers: list[RunnerMomentum]
    drifters: list[RunnerMomentum]
    sharp_moves: list[RunnerMomentum]
    total_markets_analyzed: int
    timestamp: datetime


class MomentumAnalyzer:
    """
    Analyzes price movements to detect steamers and drifters.

    Thresholds:
    - Slight: 2-5% price change
    - Moderate: 5-10% price change
    - Sharp: >10% price change
    """

    # Movement thresholds (as decimal, e.g., 0.05 = 5%)
    SLIGHT_THRESHOLD = 0.02
    MODERATE_THRESHOLD = 0.05
    SHARP_THRESHOLD = 0.10

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_current_movers(
        self,
        min_change_pct: float = 3.0,
        hours_ahead: int = 24,
        limit: int = 50,
    ) -> MomentumSummary:
        """
        Get current steamers and drifters across all active markets.

        Args:
            min_change_pct: Minimum % change to be considered a mover
            hours_ahead: Only look at markets starting within this many hours
            limit: Max results per category

        Returns:
            MomentumSummary with categorized movers
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        min_change = min_change_pct / 100.0

        # Pre-compute all time boundaries to avoid asyncpg type casting issues
        t_25m = now - timedelta(minutes=25)
        t_45m = now - timedelta(minutes=45)
        t_75m = now - timedelta(minutes=75)
        t_90m = now - timedelta(minutes=90)
        t_150m = now - timedelta(minutes=150)
        t_180m = now - timedelta(minutes=180)
        t_300m = now - timedelta(minutes=300)
        t_5h = now - timedelta(hours=5)

        # Query to get price movements
        # Compares current snapshot to snapshots from 30m, 1h, 2h, 4h ago
        query = text("""
            WITH current_prices AS (
                -- Get the latest snapshot for each market
                SELECT DISTINCT ON (ms.market_id)
                    ms.market_id,
                    ms.id as snapshot_id,
                    ms.captured_at,
                    ms.total_matched,
                    ms.ladder_data
                FROM market_snapshots ms
                JOIN markets m ON ms.market_id = m.id
                JOIN events e ON m.event_id = e.id
                WHERE e.scheduled_start > :now
                  AND e.scheduled_start < :cutoff
                  AND m.status = 'OPEN'
                ORDER BY ms.market_id, ms.captured_at DESC
            ),
            historical_prices AS (
                -- Get snapshots from ~30m, ~1h, ~2h, ~4h ago
                SELECT DISTINCT ON (ms.market_id, time_bucket)
                    ms.market_id,
                    ms.captured_at,
                    ms.total_matched,
                    ms.ladder_data,
                    CASE
                        WHEN ms.captured_at >= :t_45m AND ms.captured_at < :t_25m THEN '30m'
                        WHEN ms.captured_at >= :t_75m AND ms.captured_at < :t_45m THEN '1h'
                        WHEN ms.captured_at >= :t_150m AND ms.captured_at < :t_90m THEN '2h'
                        WHEN ms.captured_at >= :t_300m AND ms.captured_at < :t_180m THEN '4h'
                    END as time_bucket
                FROM market_snapshots ms
                JOIN markets m ON ms.market_id = m.id
                JOIN events e ON m.event_id = e.id
                WHERE e.scheduled_start > :now
                  AND e.scheduled_start < :cutoff
                  AND ms.captured_at >= :t_5h
                  AND ms.captured_at < :t_25m
                ORDER BY ms.market_id, time_bucket, ms.captured_at DESC
            ),
            price_comparison AS (
                SELECT
                    cp.market_id,
                    m.market_type,
                    e.name as event_name,
                    e.scheduled_start as event_start,
                    c.name as competition_name,
                    cp.captured_at as current_time,
                    cp.total_matched as current_matched,
                    cp.ladder_data as current_ladder,
                    hp_30m.ladder_data as ladder_30m,
                    hp_30m.total_matched as matched_30m,
                    hp_1h.ladder_data as ladder_1h,
                    hp_1h.total_matched as matched_1h,
                    hp_2h.ladder_data as ladder_2h,
                    hp_4h.ladder_data as ladder_4h
                FROM current_prices cp
                JOIN markets m ON cp.market_id = m.id
                JOIN events e ON m.event_id = e.id
                JOIN competitions c ON e.competition_id = c.id
                LEFT JOIN historical_prices hp_30m
                    ON cp.market_id = hp_30m.market_id AND hp_30m.time_bucket = '30m'
                LEFT JOIN historical_prices hp_1h
                    ON cp.market_id = hp_1h.market_id AND hp_1h.time_bucket = '1h'
                LEFT JOIN historical_prices hp_2h
                    ON cp.market_id = hp_2h.market_id AND hp_2h.time_bucket = '2h'
                LEFT JOIN historical_prices hp_4h
                    ON cp.market_id = hp_4h.market_id AND hp_4h.time_bucket = '4h'
            )
            SELECT * FROM price_comparison
            WHERE current_ladder IS NOT NULL
        """)

        result = await self.db.execute(query, {
            "now": now,
            "cutoff": cutoff,
            "t_25m": t_25m,
            "t_45m": t_45m,
            "t_75m": t_75m,
            "t_90m": t_90m,
            "t_150m": t_150m,
            "t_180m": t_180m,
            "t_300m": t_300m,
            "t_5h": t_5h,
        })
        rows = result.fetchall()

        steamers = []
        drifters = []
        sharp_moves = []

        for row in rows:
            # Parse runner data from ladder JSON
            runners = self._extract_runners_with_momentum(row)

            for runner in runners:
                # Determine primary change (use longest available timeframe)
                primary_change = (
                    runner.change_4h or runner.change_2h or
                    runner.change_1h or runner.change_30m
                )

                if primary_change is None:
                    continue

                abs_change = abs(primary_change)

                if abs_change < min_change:
                    continue

                # Classify movement
                if primary_change < 0:  # Price shortened = steamer
                    runner.movement_type = "STEAMER"
                    steamers.append(runner)
                else:  # Price lengthened = drifter
                    runner.movement_type = "DRIFTER"
                    drifters.append(runner)

                # Check for sharp moves (any timeframe)
                if abs_change >= self.SHARP_THRESHOLD:
                    runner.movement_strength = "SHARP"
                    sharp_moves.append(runner)
                elif abs_change >= self.MODERATE_THRESHOLD:
                    runner.movement_strength = "MODERATE"
                else:
                    runner.movement_strength = "SLIGHT"

        # Sort by magnitude of change
        steamers.sort(key=lambda x: x.change_2h or x.change_1h or 0)
        drifters.sort(key=lambda x: -(x.change_2h or x.change_1h or 0))
        sharp_moves.sort(key=lambda x: -abs(x.change_2h or x.change_1h or 0))

        return MomentumSummary(
            steamers=steamers[:limit],
            drifters=drifters[:limit],
            sharp_moves=sharp_moves[:limit],
            total_markets_analyzed=len(rows),
            timestamp=now,
        )

    def _extract_runners_with_momentum(self, row) -> list[RunnerMomentum]:
        """Extract runner momentum data from a price comparison row."""
        runners = []

        try:
            current_ladder = row.current_ladder
            if not current_ladder or "runners" not in current_ladder:
                return runners

            for runner_data in current_ladder.get("runners", []):
                runner_id = runner_data.get("runner_id") or runner_data.get("selection_id")
                if not runner_id:
                    continue

                # Get current prices
                back_prices = runner_data.get("back", [])
                lay_prices = runner_data.get("lay", [])

                current_back = back_prices[0]["price"] if back_prices else None
                current_lay = lay_prices[0]["price"] if lay_prices else None
                current_last = runner_data.get("last_traded")

                if not current_back:
                    continue

                # Calculate changes vs historical
                change_30m = self._calc_price_change(
                    current_back, row.ladder_30m, runner_id
                )
                change_1h = self._calc_price_change(
                    current_back, row.ladder_1h, runner_id
                )
                change_2h = self._calc_price_change(
                    current_back, row.ladder_2h, runner_id
                )
                change_4h = self._calc_price_change(
                    current_back, row.ladder_4h, runner_id
                )

                # Calculate volume change
                matched_change = None
                if row.matched_1h and row.current_matched:
                    try:
                        matched_change = float(row.current_matched - row.matched_1h)
                    except:
                        pass

                # Minutes to start
                minutes_to_start = 0
                if row.event_start:
                    delta = row.event_start - datetime.now(timezone.utc)
                    minutes_to_start = max(0, int(delta.total_seconds() / 60))

                runners.append(RunnerMomentum(
                    runner_id=runner_id,
                    runner_name=runner_data.get("name", f"Runner {runner_id}"),
                    market_id=row.market_id,
                    event_name=row.event_name,
                    competition_name=row.competition_name,
                    market_type=row.market_type,
                    event_start=row.event_start,
                    minutes_to_start=minutes_to_start,
                    current_back=current_back,
                    current_lay=current_lay or current_back * 1.02,
                    current_last_traded=current_last,
                    change_30m=change_30m,
                    change_1h=change_1h,
                    change_2h=change_2h,
                    change_4h=change_4h,
                    movement_type="STABLE",
                    movement_strength="SLIGHT",
                    total_matched=float(row.current_matched or 0),
                    matched_change_1h=matched_change,
                ))

        except Exception as e:
            logger.warning("momentum_extraction_error", error=str(e), market_id=row.market_id)

        return runners

    def _calc_price_change(
        self,
        current_price: float,
        historical_ladder: Optional[dict],
        runner_id: int
    ) -> Optional[float]:
        """
        Calculate percentage price change.

        Returns negative for steamers (price shortened),
        positive for drifters (price lengthened).
        """
        if not historical_ladder or "runners" not in historical_ladder:
            return None

        for runner in historical_ladder.get("runners", []):
            rid = runner.get("runner_id") or runner.get("selection_id")
            if rid != runner_id:
                continue

            back_prices = runner.get("back", [])
            if not back_prices:
                return None

            old_price = back_prices[0]["price"]
            if old_price <= 0:
                return None

            # (current - old) / old
            # Negative = price shortened (steamer)
            # Positive = price lengthened (drifter)
            return (current_price - old_price) / old_price

        return None


async def get_momentum_summary(
    db: AsyncSession,
    min_change_pct: float = 3.0,
    hours_ahead: int = 24,
) -> MomentumSummary:
    """Convenience function to get momentum summary."""
    analyzer = MomentumAnalyzer(db)
    return await analyzer.get_current_movers(
        min_change_pct=min_change_pct,
        hours_ahead=hours_ahead,
    )
