"""Snapshot capture service.

Captures point-in-time market state (ladder data) for profiling and scoring.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Competition, Event, Market, MarketSnapshot
from app.services.betfair_client import BetfairClient
from app.services.betfair_client.api import MarketBook

logger = structlog.get_logger(__name__)

# Betfair tick increment table
TICK_INCREMENTS = [
    (2.00, 0.01),
    (3.00, 0.02),
    (4.00, 0.05),
    (6.00, 0.10),
    (10.00, 0.20),
    (20.00, 0.50),
    (30.00, 1.00),
    (50.00, 2.00),
    (100.00, 5.00),
    (1000.00, 10.00),
]


def get_tick_size(price: float) -> float:
    """Get tick size for a given price."""
    for max_price, increment in TICK_INCREMENTS:
        if price <= max_price:
            return increment
    return 10.00


def calculate_spread_ticks(back_price: float, lay_price: float) -> float:
    """Calculate spread in tick increments."""
    if back_price <= 0 or lay_price <= 0:
        return 0

    spread = lay_price - back_price
    if spread <= 0:
        return 0

    # Use mid price for tick size
    mid_price = (back_price + lay_price) / 2
    tick_size = get_tick_size(mid_price)

    return spread / tick_size


def calculate_overround(runner_prices: list[float]) -> float:
    """
    Calculate market overround from best back prices.

    Overround = sum of implied probabilities.
    1.0 = fair market, >1.0 = bookmaker margin.
    """
    if not runner_prices or any(p <= 0 for p in runner_prices):
        return 0

    total_prob = sum(1.0 / p for p in runner_prices)
    return round(total_prob, 4)


class SnapshotCaptureService:
    """
    Service for capturing market snapshots.

    Captures ladder data (prices and volumes) for all active markets
    in non-excluded competitions.
    """

    def __init__(
        self,
        betfair_client: BetfairClient,
        session: AsyncSession,
        ladder_depth: int = 3,
        max_markets_per_batch: int = 20,
    ):
        """
        Initialize snapshot service.

        Args:
            betfair_client: Betfair API client
            session: Database session
            ladder_depth: Number of price levels per side
            max_markets_per_batch: Max markets per API call (Betfair limit)
        """
        self.betfair = betfair_client
        self.session = session
        self.ladder_depth = ladder_depth
        self.max_markets_per_batch = max_markets_per_batch

    async def get_active_markets(self) -> list[Market]:
        """
        Get all active markets for snapshot capture.

        Returns markets that are:
        - OPEN status (not closed/suspended)
        - Not in-play (pre-match only)
        - From enabled competitions
        """
        result = await self.session.execute(
            select(Market)
            .join(Event)
            .join(Competition)
            .where(
                Market.status == "OPEN",
                Market.in_play == False,
                Competition.enabled == True,
            )
        )
        return list(result.scalars().all())

    async def capture_snapshots(
        self, market_ids: list[int] | None = None
    ) -> dict[str, Any]:
        """
        Capture snapshots for active markets.

        Args:
            market_ids: Optional specific market IDs to capture.
                       If None, captures all active markets.

        Returns:
            Stats dict with counts
        """
        stats = {
            "markets_queried": 0,
            "snapshots_stored": 0,
            "markets_suspended": 0,
            "errors": 0,
            "batches_processed": 0,
            "batches_failed": 0,
        }

        # Get markets to capture
        if market_ids:
            result = await self.session.execute(
                select(Market).where(Market.id.in_(market_ids))
            )
            markets = list(result.scalars().all())
        else:
            markets = await self.get_active_markets()

        if not markets:
            logger.debug("no_active_markets")
            return stats

        stats["markets_queried"] = len(markets)

        # Group by betfair_id for API call
        betfair_ids = [m.betfair_id for m in markets]
        id_map = {m.betfair_id: m.id for m in markets}

        total_batches = (len(betfair_ids) + self.max_markets_per_batch - 1) // self.max_markets_per_batch
        logger.info(
            "snapshot_capture_starting",
            total_markets=len(markets),
            total_batches=total_batches,
            batch_size=self.max_markets_per_batch,
        )

        # Process in batches
        for i in range(0, len(betfair_ids), self.max_markets_per_batch):
            batch = betfair_ids[i : i + self.max_markets_per_batch]
            batch_num = i // self.max_markets_per_batch + 1

            try:
                books = await self.betfair.list_market_book(
                    market_ids=batch,
                    price_depth=self.ladder_depth,
                )

                batch_stored = 0
                batch_suspended = 0
                for book in books:
                    db_market_id = id_map.get(book.market_id)
                    if not db_market_id:
                        continue

                    # Check if market is still active
                    if book.status != "OPEN":
                        stats["markets_suspended"] += 1
                        batch_suspended += 1
                        await self._mark_market_status(db_market_id, book.status)
                        continue

                    if book.in_play:
                        stats["markets_suspended"] += 1
                        batch_suspended += 1
                        await self._mark_market_inplay(db_market_id)
                        continue

                    # Build ladder data
                    ladder_data = self._build_ladder_data(book)

                    # Store snapshot
                    snapshot = MarketSnapshot(
                        market_id=db_market_id,
                        captured_at=datetime.now(timezone.utc),
                        total_matched=book.total_matched,
                        total_available=book.total_available,
                        overround=Decimal(str(ladder_data.get("overround", 0))),
                        ladder_data=ladder_data,
                    )
                    self.session.add(snapshot)
                    stats["snapshots_stored"] += 1
                    batch_stored += 1

                stats["batches_processed"] += 1

                # Log progress every 100 batches or on first/last batch
                if batch_num == 1 or batch_num == total_batches or batch_num % 100 == 0:
                    logger.info(
                        "snapshot_batch_progress",
                        batch=batch_num,
                        total_batches=total_batches,
                        batch_stored=batch_stored,
                        batch_suspended=batch_suspended,
                        total_stored=stats["snapshots_stored"],
                    )

            except Exception as e:
                error_str = str(e)
                stats["batches_failed"] += 1

                # Handle TOO_MUCH_DATA - just skip batch, don't close markets
                if "TOO_MUCH_DATA" in error_str:
                    logger.warning(
                        "snapshot_batch_too_much_data",
                        batch=batch_num,
                        total_batches=total_batches,
                        batch_start=i,
                        batch_size=len(batch),
                    )
                    stats["errors"] += 1
                # Handle 400 Bad Request - might be invalid/stale market IDs
                elif "400" in error_str:
                    logger.warning(
                        "snapshot_batch_invalid_markets",
                        batch=batch_num,
                        total_batches=total_batches,
                        batch_start=i,
                        batch_size=len(batch),
                        error=error_str[:200],
                    )
                    # Only mark as CLOSED if it's not TOO_MUCH_DATA
                    for market_id in batch:
                        db_id = id_map.get(market_id)
                        if db_id:
                            await self._mark_market_status(db_id, "CLOSED")
                            stats["markets_suspended"] += 1
                else:
                    logger.error(
                        "snapshot_batch_error",
                        batch=batch_num,
                        total_batches=total_batches,
                        error=error_str,
                        batch_start=i,
                        batch_size=len(batch),
                    )
                    stats["errors"] += 1

        await self.session.commit()

        logger.info(
            "snapshots_captured",
            markets=stats["markets_queried"],
            stored=stats["snapshots_stored"],
            suspended=stats["markets_suspended"],
        )

        return stats

    def _build_ladder_data(self, book: MarketBook) -> dict[str, Any]:
        """Build ladder data structure from market book."""
        runners = []
        back_prices = []

        for runner in book.runners:
            best_back = runner.back_prices[0].price if runner.back_prices else None
            best_lay = runner.lay_prices[0].price if runner.lay_prices else None

            if best_back:
                back_prices.append(float(best_back))

            runner_data = {
                "runner_id": runner.selection_id,
                "last_traded": float(runner.last_price_traded)
                if runner.last_price_traded
                else None,
                "total_matched": float(runner.total_matched),
                "back": [
                    {"price": float(p.price), "size": float(p.size)}
                    for p in runner.back_prices
                ],
                "lay": [
                    {"price": float(p.price), "size": float(p.size)}
                    for p in runner.lay_prices
                ],
            }
            runners.append(runner_data)

        return {
            "runners": runners,
            "overround": calculate_overround(back_prices),
            "total_available": float(book.total_available),
        }

    async def _mark_market_status(self, market_id: int, status: str) -> None:
        """Update market status in database."""
        result = await self.session.execute(
            select(Market).where(Market.id == market_id)
        )
        market = result.scalar_one_or_none()
        if market:
            market.status = status

    async def _mark_market_inplay(self, market_id: int) -> None:
        """Mark market as in-play."""
        result = await self.session.execute(
            select(Market).where(Market.id == market_id)
        )
        market = result.scalar_one_or_none()
        if market:
            market.in_play = True


def extract_snapshot_metrics(snapshot: MarketSnapshot) -> dict[str, Any]:
    """
    Extract key metrics from a snapshot for profiling.

    Returns dict with:
    - spread_ticks: Best spread in ticks
    - best_depth: Total liquidity at best prices
    - depth_5_ticks: Liquidity within 5 ticks
    - mid_price: Average of best back/lay
    """
    ladder = snapshot.ladder_data
    runners = ladder.get("runners", [])

    if not runners:
        return {
            "spread_ticks": 0,
            "best_depth": 0,
            "depth_5_ticks": 0,
            "mid_price": 0,
        }

    # Aggregate across runners
    total_spread_ticks = 0
    total_best_depth = 0
    total_depth_5 = 0
    mid_prices = []
    valid_runners = 0

    for runner in runners:
        back = runner.get("back", [])
        lay = runner.get("lay", [])

        if not back or not lay:
            continue

        best_back = back[0]["price"]
        best_lay = lay[0]["price"]
        best_back_size = back[0]["size"]
        best_lay_size = lay[0]["size"]

        # Spread
        spread = calculate_spread_ticks(best_back, best_lay)
        total_spread_ticks += spread

        # Best depth
        total_best_depth += best_back_size + best_lay_size

        # Depth within 5 ticks
        tick_size = get_tick_size((best_back + best_lay) / 2)
        for level in back:
            if best_back - level["price"] <= 5 * tick_size:
                total_depth_5 += level["size"]
        for level in lay:
            if level["price"] - best_lay <= 5 * tick_size:
                total_depth_5 += level["size"]

        # Mid price
        mid_prices.append((best_back + best_lay) / 2)
        valid_runners += 1

    avg_spread = total_spread_ticks / valid_runners if valid_runners > 0 else 0
    avg_mid = sum(mid_prices) / len(mid_prices) if mid_prices else 0

    return {
        "spread_ticks": avg_spread,
        "best_depth": total_best_depth,
        "depth_5_ticks": total_depth_5,
        "mid_price": avg_mid,
    }
