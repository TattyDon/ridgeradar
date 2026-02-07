"""Hypothesis-based Signal Engine.

Evaluates trading hypotheses against live market data to generate
shadow trading decisions. Supports multiple concurrent hypotheses
with different entry criteria and selection logic.

Key hypothesis types:
- steam_follower: Back selections showing significant price shortening
- drift_fader: Lay selections showing significant price lengthening
- score_based: Traditional score-threshold based entry

This is PAPER TRADING only. No real money is ever at risk.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Competition,
    Event,
    ExploitabilityScore,
    Market,
    MarketSnapshot,
    Runner,
    ShadowDecision,
    TradingHypothesis,
)

logger = structlog.get_logger(__name__)


@dataclass
class MomentumSignal:
    """A detected momentum signal for a runner."""
    market_id: int
    runner_id: int
    runner_betfair_id: int
    runner_name: str
    event_name: str
    competition_id: int
    competition_name: str
    market_type: str
    scheduled_start: datetime
    minutes_to_start: int

    # Current prices
    back_price: Decimal
    lay_price: Decimal
    spread_pct: Decimal
    total_matched: Decimal
    available_to_back: Decimal
    available_to_lay: Decimal

    # Price changes (negative = steaming, positive = drifting)
    change_30m: Optional[Decimal]
    change_1h: Optional[Decimal]
    change_2h: Optional[Decimal]

    # Score context
    exploitability_score: Optional[Decimal]
    score_id: Optional[int]


@dataclass
class HypothesisMatch:
    """A signal that matches a hypothesis's entry criteria."""
    hypothesis: TradingHypothesis
    signal: MomentumSignal
    match_reason: str
    decision_type: str  # BACK or LAY


class HypothesisEngine:
    """
    Evaluates trading hypotheses against market signals.

    For each active hypothesis, checks if current market conditions
    match the entry criteria and generates shadow decisions accordingly.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_hypotheses(self) -> list[TradingHypothesis]:
        """Get all enabled trading hypotheses."""
        result = await self.db.execute(
            select(TradingHypothesis).where(TradingHypothesis.enabled == True)
        )
        return list(result.scalars().all())

    async def find_momentum_signals(
        self,
        min_change_pct: float = 3.0,
        hours_ahead: int = 24,
        min_score: float = 0,
    ) -> list[MomentumSignal]:
        """
        Find all runners showing significant price movement.

        Combines momentum analysis with exploitability scores to find
        potential trading opportunities.
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)

        # Time boundaries for historical comparison
        t_25m = now - timedelta(minutes=25)
        t_45m = now - timedelta(minutes=45)
        t_75m = now - timedelta(minutes=75)
        t_90m = now - timedelta(minutes=90)
        t_150m = now - timedelta(minutes=150)
        t_180m = now - timedelta(minutes=180)
        t_300m = now - timedelta(minutes=300)
        t_5h = now - timedelta(hours=5)

        query = text("""
            WITH current_prices AS (
                SELECT DISTINCT ON (ms.market_id)
                    ms.market_id,
                    ms.captured_at,
                    ms.total_matched,
                    ms.ladder_data
                FROM market_snapshots ms
                JOIN markets m ON ms.market_id = m.id
                JOIN events e ON m.event_id = e.id
                JOIN competitions c ON e.competition_id = c.id
                WHERE e.scheduled_start > :now
                  AND e.scheduled_start < :cutoff
                  AND m.status = 'OPEN'
                  AND (m.in_play = false OR m.in_play IS NULL)
                  AND c.enabled = true
                  AND m.market_type NOT IN ('ASIAN_HANDICAP', 'HANDICAP')  -- Exclude handicap (extreme swings)
                ORDER BY ms.market_id, ms.captured_at DESC
            ),
            historical_30m AS (
                SELECT DISTINCT ON (ms.market_id)
                    ms.market_id, ms.ladder_data
                FROM market_snapshots ms
                WHERE ms.captured_at >= :t_45m AND ms.captured_at < :t_25m
                ORDER BY ms.market_id, ms.captured_at DESC
            ),
            historical_1h AS (
                SELECT DISTINCT ON (ms.market_id)
                    ms.market_id, ms.ladder_data
                FROM market_snapshots ms
                WHERE ms.captured_at >= :t_90m AND ms.captured_at < :t_45m
                ORDER BY ms.market_id, ms.captured_at DESC
            ),
            historical_2h AS (
                SELECT DISTINCT ON (ms.market_id)
                    ms.market_id, ms.ladder_data
                FROM market_snapshots ms
                WHERE ms.captured_at >= :t_180m AND ms.captured_at < :t_90m
                ORDER BY ms.market_id, ms.captured_at DESC
            ),
            latest_scores AS (
                SELECT DISTINCT ON (market_id)
                    id as score_id, market_id, total_score
                FROM exploitability_scores
                ORDER BY market_id, scored_at DESC
            )
            SELECT
                cp.market_id,
                m.market_type,
                e.id as event_id,
                e.name as event_name,
                e.scheduled_start,
                c.id as competition_id,
                c.name as competition_name,
                cp.total_matched,
                cp.ladder_data as current_ladder,
                h30.ladder_data as ladder_30m,
                h1.ladder_data as ladder_1h,
                h2.ladder_data as ladder_2h,
                ls.score_id,
                ls.total_score
            FROM current_prices cp
            JOIN markets m ON cp.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            LEFT JOIN historical_30m h30 ON cp.market_id = h30.market_id
            LEFT JOIN historical_1h h1 ON cp.market_id = h1.market_id
            LEFT JOIN historical_2h h2 ON cp.market_id = h2.market_id
            LEFT JOIN latest_scores ls ON cp.market_id = ls.market_id
            WHERE cp.ladder_data IS NOT NULL
              AND (ls.total_score IS NULL OR ls.total_score >= :min_score)
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
            "min_score": min_score,
        })
        rows = result.fetchall()

        # Get runner info
        market_ids = [row.market_id for row in rows]
        runners_by_market = await self._get_runners_by_market(market_ids)

        signals = []
        min_change = min_change_pct / 100.0

        for row in rows:
            # Extract signals for each runner in the market
            market_signals = self._extract_momentum_signals(
                row, runners_by_market.get(row.market_id, []), min_change
            )
            signals.extend(market_signals)

        return signals

    async def _get_runners_by_market(
        self, market_ids: list[int]
    ) -> dict[int, list[tuple[int, int, str]]]:
        """Get runners for markets. Returns {market_id: [(id, betfair_id, name), ...]}"""
        if not market_ids:
            return {}

        result = await self.db.execute(text("""
            SELECT id, market_id, betfair_id, name
            FROM runners
            WHERE market_id = ANY(:market_ids)
        """), {"market_ids": market_ids})

        runners_by_market: dict[int, list[tuple[int, int, str]]] = {}
        for row in result:
            if row.market_id not in runners_by_market:
                runners_by_market[row.market_id] = []
            runners_by_market[row.market_id].append((row.id, row.betfair_id, row.name))

        return runners_by_market

    def _extract_momentum_signals(
        self,
        row,
        runners: list[tuple[int, int, str]],
        min_change: float,
    ) -> list[MomentumSignal]:
        """Extract momentum signals from a market row."""
        signals = []

        try:
            current_ladder = row.current_ladder
            if not current_ladder or "runners" not in current_ladder:
                return signals

            runner_map = {r[1]: (r[0], r[2]) for r in runners}  # betfair_id -> (id, name)
            now = datetime.now(timezone.utc)
            minutes_to_start = max(0, int((row.scheduled_start - now).total_seconds() / 60))

            for ladder_runner in current_ladder.get("runners", []):
                runner_betfair_id = ladder_runner.get("runner_id") or ladder_runner.get("selection_id")
                if not runner_betfair_id or runner_betfair_id not in runner_map:
                    continue

                runner_id, runner_name = runner_map[runner_betfair_id]

                # Get current prices
                back_prices = ladder_runner.get("back", [])
                lay_prices = ladder_runner.get("lay", [])

                if not back_prices:
                    continue

                back_price = Decimal(str(back_prices[0].get("price", 0)))
                lay_price = Decimal(str(lay_prices[0].get("price", back_price * Decimal("1.02")))) if lay_prices else back_price * Decimal("1.02")
                available_to_back = Decimal(str(back_prices[0].get("size", 0)))
                available_to_lay = Decimal(str(lay_prices[0].get("size", 0))) if lay_prices else Decimal("0")

                if back_price <= 0:
                    continue

                # Filter out extreme prices (not useful for trading)
                if back_price < Decimal("1.10") or back_price > Decimal("50"):
                    continue

                # Calculate spread
                spread_pct = ((lay_price - back_price) / back_price) * 100

                # Calculate price changes
                change_30m = self._calc_price_change(back_price, row.ladder_30m, runner_betfair_id)
                change_1h = self._calc_price_change(back_price, row.ladder_1h, runner_betfair_id)
                change_2h = self._calc_price_change(back_price, row.ladder_2h, runner_betfair_id)

                # Check if this runner has significant movement
                primary_change = change_2h or change_1h or change_30m
                if primary_change is None or abs(float(primary_change)) < min_change:
                    continue

                # Filter out extreme changes (>100% is data noise)
                if abs(float(primary_change)) > 100:
                    continue

                signals.append(MomentumSignal(
                    market_id=row.market_id,
                    runner_id=runner_id,
                    runner_betfair_id=runner_betfair_id,
                    runner_name=runner_name or f"Runner {runner_betfair_id}",
                    event_name=row.event_name,
                    competition_id=row.competition_id,
                    competition_name=row.competition_name,
                    market_type=row.market_type,
                    scheduled_start=row.scheduled_start,
                    minutes_to_start=minutes_to_start,
                    back_price=back_price,
                    lay_price=lay_price,
                    spread_pct=spread_pct,
                    total_matched=Decimal(str(row.total_matched or 0)),
                    available_to_back=available_to_back,
                    available_to_lay=available_to_lay,
                    change_30m=change_30m,
                    change_1h=change_1h,
                    change_2h=change_2h,
                    exploitability_score=Decimal(str(row.total_score)) if row.total_score else None,
                    score_id=row.score_id,
                ))

        except Exception as e:
            logger.warning("signal_extraction_error", market_id=row.market_id, error=str(e))

        return signals

    def _calc_price_change(
        self,
        current_price: Decimal,
        historical_ladder: Optional[dict],
        runner_betfair_id: int,
    ) -> Optional[Decimal]:
        """Calculate percentage price change from historical ladder."""
        if not historical_ladder or "runners" not in historical_ladder:
            return None

        for runner in historical_ladder.get("runners", []):
            rid = runner.get("runner_id") or runner.get("selection_id")
            if rid != runner_betfair_id:
                continue

            back_prices = runner.get("back", [])
            if not back_prices:
                return None

            old_price = Decimal(str(back_prices[0]["price"]))
            if old_price <= 0:
                return None

            # Negative = steaming (price shortened), Positive = drifting
            return ((current_price - old_price) / old_price) * 100

        return None

    def matches_hypothesis(
        self,
        hypothesis: TradingHypothesis,
        signal: MomentumSignal,
    ) -> Optional[HypothesisMatch]:
        """
        Check if a signal matches a hypothesis's entry criteria.

        Returns HypothesisMatch if criteria are met, None otherwise.
        """
        criteria = hypothesis.entry_criteria
        reasons = []

        # Check score threshold
        min_score = criteria.get("min_score", 0)
        if signal.exploitability_score is not None:
            if float(signal.exploitability_score) < min_score:
                return None
            reasons.append(f"score {signal.exploitability_score:.0f} >= {min_score}")
        elif min_score > 0:
            return None  # Require score if threshold set

        # Check time window
        min_minutes = criteria.get("min_minutes_to_start", 0)
        max_minutes = criteria.get("max_minutes_to_start", 1440)
        if signal.minutes_to_start < min_minutes or signal.minutes_to_start > max_minutes:
            return None
        reasons.append(f"{signal.minutes_to_start}m to start")

        # Check spread
        max_spread = criteria.get("max_spread_pct", 10.0)
        if float(signal.spread_pct) > max_spread:
            return None

        # Check liquidity
        min_matched = criteria.get("min_total_matched", 0)
        if float(signal.total_matched) < min_matched:
            return None

        # Check market type filter
        market_types = criteria.get("market_type_filter")
        if market_types and signal.market_type not in market_types:
            return None

        # Check competition filter
        competition_filter = criteria.get("competition_filter")
        if competition_filter and signal.competition_id not in competition_filter:
            return None

        # Check momentum criteria
        price_change_direction = criteria.get("price_change_direction")
        min_change = criteria.get("min_price_change_pct", 0)
        change_window = criteria.get("price_change_window_minutes", 60)

        # Select the appropriate change based on window
        if change_window <= 30:
            change = signal.change_30m
        elif change_window <= 60:
            change = signal.change_1h or signal.change_30m
        else:
            change = signal.change_2h or signal.change_1h or signal.change_30m

        if change is None and min_change > 0:
            return None

        if change is not None:
            change_float = float(change)

            if price_change_direction == "steaming":
                # Steaming = price shortening = negative change
                if change_float >= 0 or abs(change_float) < min_change:
                    return None
                reasons.append(f"steaming {abs(change_float):.1f}%")
            elif price_change_direction == "drifting":
                # Drifting = price lengthening = positive change
                if change_float <= 0 or change_float < min_change:
                    return None
                reasons.append(f"drifting {change_float:.1f}%")
            elif min_change > 0:
                # Any direction, just need minimum change
                if abs(change_float) < min_change:
                    return None
                direction = "steaming" if change_float < 0 else "drifting"
                reasons.append(f"{direction} {abs(change_float):.1f}%")

        # Determine decision type
        decision_type = hypothesis.decision_type
        if price_change_direction == "steaming":
            decision_type = "BACK"  # Follow the steam
        elif price_change_direction == "drifting" and hypothesis.selection_logic == "contrarian":
            decision_type = "LAY"  # Fade the drift

        return HypothesisMatch(
            hypothesis=hypothesis,
            signal=signal,
            match_reason=", ".join(reasons),
            decision_type=decision_type,
        )

    async def check_existing_decision(
        self,
        market_id: int,
        hypothesis_name: str,
    ) -> bool:
        """Check if we already have a decision for this market/hypothesis."""
        result = await self.db.execute(text("""
            SELECT 1 FROM shadow_decisions
            WHERE market_id = :market_id
              AND hypothesis_name = :hypothesis_name
            LIMIT 1
        """), {"market_id": market_id, "hypothesis_name": hypothesis_name})
        return result.fetchone() is not None

    async def create_shadow_decision(
        self,
        match: HypothesisMatch,
    ) -> ShadowDecision:
        """Create a shadow decision from a hypothesis match."""
        signal = match.signal
        hypothesis = match.hypothesis

        # Get or create the score reference
        score_id = signal.score_id

        # Build niche identifier
        niche = f"{signal.competition_name} - {signal.market_type}"

        decision = ShadowDecision(
            market_id=signal.market_id,
            runner_id=signal.runner_id,
            decision_type=match.decision_type,
            score_id=score_id,
            trigger_score=signal.exploitability_score or Decimal("0"),
            trigger_reason=f"Hypothesis '{hypothesis.name}': {match.match_reason}",
            decision_at=datetime.now(timezone.utc),
            minutes_to_start=signal.minutes_to_start,
            entry_back_price=signal.back_price,
            entry_lay_price=signal.lay_price,
            entry_spread=signal.spread_pct,
            available_to_back=signal.available_to_back,
            available_to_lay=signal.available_to_lay,
            theoretical_stake=Decimal("10.00"),
            outcome="PENDING",
            niche=niche,
            competition_id=signal.competition_id,
            hypothesis_id=hypothesis.id,
            hypothesis_name=hypothesis.name,
            price_change_30m=signal.change_30m,
            price_change_1h=signal.change_1h,
            price_change_2h=signal.change_2h,
        )

        self.db.add(decision)
        return decision

    async def evaluate_hypotheses(self) -> dict[str, Any]:
        """
        Main entry point: evaluate all active hypotheses against current signals.

        Returns summary statistics.
        """
        stats = {
            "hypotheses_evaluated": 0,
            "signals_found": 0,
            "decisions_created": 0,
            "by_hypothesis": {},
            "errors": 0,
        }

        try:
            # Get active hypotheses
            hypotheses = await self.get_active_hypotheses()
            stats["hypotheses_evaluated"] = len(hypotheses)

            if not hypotheses:
                logger.info("no_active_hypotheses")
                return stats

            # Find momentum signals (cast wide net, let hypothesis filter)
            signals = await self.find_momentum_signals(
                min_change_pct=2.0,  # Low threshold, hypotheses will filter
                hours_ahead=24,
                min_score=0,
            )
            stats["signals_found"] = len(signals)

            # Evaluate each hypothesis against each signal
            for hypothesis in hypotheses:
                hypothesis_stats = {"matched": 0, "created": 0, "skipped_existing": 0}

                for signal in signals:
                    try:
                        match = self.matches_hypothesis(hypothesis, signal)
                        if not match:
                            continue

                        hypothesis_stats["matched"] += 1

                        # Check if we already have a decision
                        if await self.check_existing_decision(
                            signal.market_id, hypothesis.name
                        ):
                            hypothesis_stats["skipped_existing"] += 1
                            continue

                        # Create shadow decision
                        decision = await self.create_shadow_decision(match)
                        hypothesis_stats["created"] += 1
                        stats["decisions_created"] += 1

                        logger.info(
                            "hypothesis_decision_created",
                            hypothesis=hypothesis.name,
                            market_id=signal.market_id,
                            runner=signal.runner_name,
                            decision_type=match.decision_type,
                            reason=match.match_reason,
                            entry_price=float(
                                signal.back_price if match.decision_type == "BACK"
                                else signal.lay_price
                            ),
                        )

                    except Exception as e:
                        logger.error(
                            "hypothesis_evaluation_error",
                            hypothesis=hypothesis.name,
                            market_id=signal.market_id,
                            error=str(e),
                        )
                        stats["errors"] += 1

                stats["by_hypothesis"][hypothesis.name] = hypothesis_stats

            await self.db.commit()
            logger.info("hypothesis_evaluation_complete", **stats)

        except Exception as e:
            logger.error("hypothesis_evaluation_failed", error=str(e))
            await self.db.rollback()
            raise

        return stats


async def evaluate_all_hypotheses(db: AsyncSession) -> dict[str, Any]:
    """Convenience function to evaluate all hypotheses."""
    engine = HypothesisEngine(db)
    return await engine.evaluate_hypotheses()
