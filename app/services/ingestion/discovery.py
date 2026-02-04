"""Market discovery service.

Discovers competitions, events, and markets from Betfair.

PHILOSOPHY: Ingest broadly, filter by score.
- We don't pre-judge which leagues are "good" based on names
- The scoring engine penalises high-volume efficient markets automatically
- Hard exclusions only for things that waste API quota (wrong sports, friendlies, etc.)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Competition, Event, Market, Runner, Sport

logger = structlog.get_logger(__name__)


def should_exclude_competition(
    competition_name: str,
    config: dict[str, Any] | None = None,
) -> bool:
    """
    Check if a competition should be hard-excluded from ingestion.

    This is NOT about market efficiency (the scoring engine handles that).
    This is about saving API quota on things we definitely don't want:
    - Wrong sports (if somehow fetched)
    - Youth/reserve/amateur matches
    - Friendlies

    Args:
        competition_name: Name of the competition from Betfair
        config: Optional configuration dict

    Returns:
        True if competition should be excluded, False otherwise
    """
    if config is None:
        config = _load_default_config()

    hard_exclusions = config.get("global", {}).get("hard_exclusions", {})
    patterns = hard_exclusions.get("competition_patterns", [])

    name_lower = competition_name.lower()

    for pattern in patterns:
        if pattern.lower() in name_lower:
            logger.debug(
                "competition_hard_excluded",
                name=competition_name,
                matched_pattern=pattern,
            )
            return True

    return False


def _load_default_config() -> dict[str, Any]:
    """Load configuration from defaults.yaml."""
    config_path = Path(__file__).parent.parent.parent / "config" / "defaults.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


class MarketDiscoveryService:
    """
    Service for discovering markets from Betfair.

    Philosophy:
    - Ingest ALL competitions for enabled sports (except hard exclusions)
    - Let the scoring engine filter based on actual market characteristics
    - Track competition-level stats to learn which ones consistently score well

    Hard exclusions only:
    - Youth/Reserve/Amateur matches
    - Friendlies
    - Sports we don't care about
    """

    def __init__(
        self,
        betfair_client: "BetfairClient",
        session: AsyncSession,
        config: dict[str, Any] | None = None,
    ):
        """
        Initialize discovery service.

        Args:
            betfair_client: Betfair API client
            session: Database session
            config: Optional configuration
        """
        self.betfair = betfair_client
        self.session = session
        self.config = config or _load_default_config()

    async def discover_all(self) -> dict[str, int]:
        """
        Run full discovery process.

        Returns:
            Dict with counts of discovered/updated entities
        """
        stats = {
            "sports": 0,
            "competitions": 0,
            "competitions_excluded": 0,
            "events": 0,
            "markets": 0,
            "runners": 0,
        }

        # 1. Discover sports
        sports = await self._discover_sports()
        stats["sports"] = len(sports)

        # 2. Discover competitions (with minimal hard exclusions)
        competitions = await self._discover_competitions(sports)
        stats["competitions"] = len([c for c in competitions if c["enabled"]])
        stats["competitions_excluded"] = len([c for c in competitions if not c["enabled"]])

        # 3. Discover events for enabled competitions
        enabled_comps = [c for c in competitions if c["enabled"]]
        events = await self._discover_events(enabled_comps)
        stats["events"] = len(events)

        # 4. Discover markets
        markets = await self._discover_markets(events)
        stats["markets"] = len(markets)

        # 5. Mark stale events as closed
        await self._mark_stale_events()

        logger.info("discovery_complete", **stats)
        return stats

    async def _discover_sports(self) -> list[dict[str, Any]]:
        """Fetch and upsert sports."""
        global_config = self.config.get("global", {})
        enabled_sports = global_config.get("enabled_sports", ["soccer", "tennis"])

        # Sport name to Betfair ID mapping
        sport_mapping = {
            "soccer": "1",
            "tennis": "2",
            "golf": "3",
            "cricket": "4",
            "rugby_union": "5",
            "boxing": "6",
            "horse_racing": "7",
            "motor_sport": "8",
        }

        sports = []
        for sport_name in enabled_sports:
            betfair_id = sport_mapping.get(sport_name.lower())
            if not betfair_id:
                continue

            stmt = insert(Sport).values(
                betfair_id=betfair_id,
                name=sport_name.title(),
                enabled=True,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["betfair_id"],
                set_={"name": sport_name.title(), "enabled": True},
            )
            await self.session.execute(stmt)

            sports.append({"betfair_id": betfair_id, "name": sport_name})

        await self.session.commit()
        return sports

    async def _discover_competitions(
        self, sports: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Fetch and upsert competitions.

        Only applies hard exclusions (friendlies, youth, etc.).
        Everything else gets ingested and the scoring engine filters.
        """
        sport_ids = [s["betfair_id"] for s in sports]

        # Fetch from Betfair
        bf_competitions = await self.betfair.list_competitions(sport_ids=sport_ids)

        # Get sport ID mapping from database
        result = await self.session.execute(select(Sport))
        db_sports = {s.betfair_id: s.id for s in result.scalars()}

        competitions = []
        for comp in bf_competitions:
            # Only hard exclusions (friendlies, youth, etc.)
            excluded = should_exclude_competition(comp.name, self.config)

            # Find matching sport (default to soccer)
            sport_db_id = db_sports.get("1", 1)  # Default soccer

            stmt = insert(Competition).values(
                betfair_id=comp.id,
                sport_id=sport_db_id,
                name=comp.name,
                country_code=comp.region,
                enabled=not excluded,
                tier="active",  # No more tier classification - scoring handles it
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["betfair_id"],
                set_={
                    "name": comp.name,
                    "country_code": comp.region,
                    "enabled": not excluded,
                },
            )
            await self.session.execute(stmt)

            competitions.append(
                {
                    "betfair_id": comp.id,
                    "name": comp.name,
                    "enabled": not excluded,
                }
            )

            if excluded:
                logger.debug("competition_hard_excluded", name=comp.name)

        await self.session.commit()
        return competitions

    async def _discover_events(
        self, competitions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Fetch and upsert events for enabled competitions."""
        global_config = self.config.get("global", {})
        lookahead_hours = global_config.get("lookahead_hours", 72)

        now = datetime.now(timezone.utc)
        to_time = now + timedelta(hours=lookahead_hours)

        # Get competition ID mapping from database
        result = await self.session.execute(select(Competition))
        comp_map = {c.betfair_id: c.id for c in result.scalars()}

        events = []

        # Process in batches to avoid API limits
        batch_size = 20
        comp_ids = [c["betfair_id"] for c in competitions]

        for i in range(0, len(comp_ids), batch_size):
            batch = comp_ids[i : i + batch_size]

            bf_events = await self.betfair.list_events(
                competition_ids=batch,
                from_time=now,
                to_time=to_time,
            )

            for event in bf_events:
                # Find competition - need to determine from event
                comp_db_id = None
                for comp in competitions:
                    if comp["betfair_id"] in batch:
                        comp_db_id = comp_map.get(comp["betfair_id"])
                        break

                if not comp_db_id:
                    comp_db_id = comp_map.get(batch[0])

                stmt = insert(Event).values(
                    betfair_id=event.id,
                    competition_id=comp_db_id,
                    name=event.name,
                    scheduled_start=event.open_date or now,
                    status="SCHEDULED",
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["betfair_id"],
                    set_={
                        "name": event.name,
                        "scheduled_start": event.open_date or now,
                    },
                )
                await self.session.execute(stmt)

                events.append(
                    {
                        "betfair_id": event.id,
                        "name": event.name,
                    }
                )

        await self.session.commit()
        return events

    async def _discover_markets(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Fetch and upsert markets for discovered events."""
        global_config = self.config.get("global", {})
        market_types = global_config.get(
            "enabled_market_types", ["MATCH_ODDS", "OVER_UNDER_25"]
        )

        # Get event ID mapping from database
        result = await self.session.execute(select(Event))
        event_map = {e.betfair_id: e.id for e in result.scalars()}

        markets = []

        # Process in batches
        batch_size = 50
        event_ids = [e["betfair_id"] for e in events]

        for i in range(0, len(event_ids), batch_size):
            batch = event_ids[i : i + batch_size]

            bf_markets = await self.betfair.list_market_catalogue(
                event_ids=batch,
                market_types=market_types,
                max_results=200,
            )

            for market in bf_markets:
                event_db_id = event_map.get(market.event_id)
                if not event_db_id:
                    continue

                stmt = insert(Market).values(
                    betfair_id=market.market_id,
                    event_id=event_db_id,
                    name=market.market_name,
                    market_type=market.market_type,
                    total_matched=market.total_matched,
                    status="OPEN",
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["betfair_id"],
                    set_={
                        "name": market.market_name,
                        "total_matched": market.total_matched,
                    },
                )
                await self.session.execute(stmt)

                markets.append(
                    {
                        "betfair_id": market.market_id,
                        "name": market.market_name,
                        "runners": market.runners,
                    }
                )

        await self.session.commit()

        # Upsert runners
        result = await self.session.execute(select(Market))
        market_map = {m.betfair_id: m.id for m in result.scalars()}

        for market in markets:
            market_db_id = market_map.get(market["betfair_id"])
            if not market_db_id:
                continue

            for runner in market.get("runners", []):
                stmt = insert(Runner).values(
                    betfair_id=runner.selection_id,
                    market_id=market_db_id,
                    name=runner.runner_name,
                    sort_priority=runner.sort_priority,
                    status="ACTIVE",
                )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["betfair_id", "market_id"],
                )
                await self.session.execute(stmt)

        await self.session.commit()
        return markets

    async def _mark_stale_events(self) -> int:
        """Mark events with passed start time as CLOSED."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=4)  # 4 hours after start

        result = await self.session.execute(
            select(Event).where(
                Event.scheduled_start < cutoff,
                Event.status == "SCHEDULED",
            )
        )
        stale_events = result.scalars().all()

        for event in stale_events:
            event.status = "CLOSED"

        await self.session.commit()

        if stale_events:
            logger.info("marked_stale_events", count=len(stale_events))

        return len(stale_events)


# Keep old function for backwards compatibility but mark deprecated
def classify_competition_tier(
    competition_name: str,
    config: dict[str, Any] | None = None,
) -> str:
    """
    DEPRECATED: Use should_exclude_competition() instead.

    The scoring engine now handles market filtering based on actual data,
    not name-based tier classification.

    This function now returns 'active' for non-excluded competitions
    and 'excluded' only for hard exclusions.
    """
    if should_exclude_competition(competition_name, config):
        return "excluded"
    return "active"
