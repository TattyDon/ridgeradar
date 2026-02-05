"""Analytics API endpoints.

Provides aggregated statistics and insights about scoring patterns.
This is the analytical backbone for understanding what drives good scores.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, case, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.domain import (
    Competition,
    CompetitionStats,
    Event,
    ExploitabilityScore,
    Market,
    MarketClosingData,
    MarketProfileDaily,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ============================================================================
# Response Models
# ============================================================================

class ScoreBandStats(BaseModel):
    """Statistics for a score band."""
    band: str
    count: int
    avg_spread_score: float
    avg_volatility_score: float
    avg_update_score: float
    avg_depth_score: float
    avg_volume_penalty: float


class RawMetricStats(BaseModel):
    """Raw metric statistics for a score band."""
    band: str
    count: int
    avg_spread_ticks: float
    min_spread: float
    max_spread: float
    avg_volatility: float
    avg_update_rate: float
    avg_depth: float
    avg_volume: float
    min_volume: float
    max_volume: float


class CompetitionRanking(BaseModel):
    """Competition ranking entry."""
    name: str
    country_code: str | None
    markets_scored: int
    avg_score: float
    max_score: float
    high_value_markets: int
    excellent_markets: int
    avg_spread: float
    avg_volume: float


class TimeBucketStats(BaseModel):
    """Statistics by time bucket."""
    bucket: str
    total_scores: int
    avg_score: float
    max_score: float
    high_value: int
    excellent: int
    pct_high_value: float


class OddsBandStats(BaseModel):
    """Statistics by odds band."""
    band: str
    total_scores: int
    avg_score: float
    max_score: float
    high_value: int
    pct_high_value: float


class VolumeBandStats(BaseModel):
    """Statistics by volume band."""
    band: str
    market_count: int
    avg_score: float
    avg_volume_penalty: float
    high_value: int


class HighScoringMarket(BaseModel):
    """High scoring market details."""
    competition: str
    event: str
    market: str
    total_score: float
    time_bucket: str
    odds_band: str
    spread_score: float
    volatility_score: float
    update_score: float
    depth_score: float
    volume_penalty: float
    avg_spread_ticks: float | None
    price_volatility: float | None
    avg_depth_best: float | None
    total_matched_volume: float | None


class AnalyticsSummary(BaseModel):
    """Overall analytics summary."""
    total_markets: int
    excellent_70_plus: int
    high_55_70: int
    medium_40_55: int
    low_under_40: int
    overall_avg_score: float
    highest_score: float


class ClosingDataSummary(BaseModel):
    """Summary of closing data capture."""
    total_captured: int
    with_closing_odds: int
    with_final_score: int
    with_results: int
    high_score_captured: int  # 55+
    excellent_score_captured: int  # 70+


class ClosingDataItem(BaseModel):
    """Individual closing data record."""
    market_id: int
    competition: str
    event: str
    market_name: str
    final_score: float | None
    closing_back_price: float | None
    closing_lay_price: float | None
    winner: str | None
    minutes_to_start: int | None
    odds_captured_at: str | None
    settled_at: str | None


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(db: AsyncSession = Depends(get_db)):
    """
    Get overall analytics summary.

    Quick overview of today's score distribution.
    """
    query = select(
        func.count(ExploitabilityScore.id).label("total"),
        func.count(ExploitabilityScore.id).filter(
            ExploitabilityScore.total_score >= 70
        ).label("excellent"),
        func.count(ExploitabilityScore.id).filter(
            ExploitabilityScore.total_score >= 55,
            ExploitabilityScore.total_score < 70
        ).label("high"),
        func.count(ExploitabilityScore.id).filter(
            ExploitabilityScore.total_score >= 40,
            ExploitabilityScore.total_score < 55
        ).label("medium"),
        func.count(ExploitabilityScore.id).filter(
            ExploitabilityScore.total_score < 40
        ).label("low"),
        func.avg(ExploitabilityScore.total_score).label("avg_score"),
        func.max(ExploitabilityScore.total_score).label("max_score"),
    ).join(
        Market, ExploitabilityScore.market_id == Market.id
    ).join(
        Event, Market.event_id == Event.id
    ).join(
        Competition, Event.competition_id == Competition.id
    ).where(Competition.enabled == True)

    result = await db.execute(query)
    row = result.one()

    return AnalyticsSummary(
        total_markets=row.total or 0,
        excellent_70_plus=row.excellent or 0,
        high_55_70=row.high or 0,
        medium_40_55=row.medium or 0,
        low_under_40=row.low or 0,
        overall_avg_score=float(row.avg_score or 0),
        highest_score=float(row.max_score or 0),
    )


@router.get("/score-components", response_model=list[ScoreBandStats])
async def get_score_components(db: AsyncSession = Depends(get_db)):
    """
    Get score component analysis by band.

    Understand which components contribute most to high scores.
    """
    # Use raw SQL with CTE to avoid GROUP BY alias issues
    query = text("""
        WITH scored AS (
            SELECT
                es.total_score,
                es.spread_score,
                es.volatility_score,
                es.update_score,
                es.depth_score,
                es.volume_penalty,
                CASE
                    WHEN es.total_score >= 70 THEN 'Excellent (70+)'
                    WHEN es.total_score >= 55 THEN 'High (55-70)'
                    WHEN es.total_score >= 40 THEN 'Medium (40-55)'
                    ELSE 'Low (<40)'
                END AS band
            FROM exploitability_scores es
            JOIN markets m ON es.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            WHERE c.enabled = true
        )
        SELECT
            band,
            COUNT(*) AS count,
            ROUND(AVG(spread_score)::numeric, 1) AS avg_spread_score,
            ROUND(AVG(volatility_score)::numeric, 1) AS avg_volatility_score,
            ROUND(AVG(update_score)::numeric, 1) AS avg_update_score,
            ROUND(AVG(depth_score)::numeric, 1) AS avg_depth_score,
            ROUND(AVG(volume_penalty)::numeric, 1) AS avg_volume_penalty
        FROM scored
        GROUP BY band
        ORDER BY
            CASE band
                WHEN 'Excellent (70+)' THEN 1
                WHEN 'High (55-70)' THEN 2
                WHEN 'Medium (40-55)' THEN 3
                ELSE 4
            END
    """)

    result = await db.execute(query)
    rows = result.all()

    return [
        ScoreBandStats(
            band=row.band,
            count=row.count,
            avg_spread_score=float(row.avg_spread_score or 0),
            avg_volatility_score=float(row.avg_volatility_score or 0),
            avg_update_score=float(row.avg_update_score or 0),
            avg_depth_score=float(row.avg_depth_score or 0),
            avg_volume_penalty=float(row.avg_volume_penalty or 0),
        )
        for row in rows
    ]


@router.get("/raw-metrics", response_model=list[RawMetricStats])
async def get_raw_metrics(db: AsyncSession = Depends(get_db)):
    """
    Get raw metric ranges by score band.

    What are the actual spread/volatility/volume values for each score band?
    """
    # Use CTE and get latest profile per market (not just CURRENT_DATE)
    query = text("""
        WITH latest_profiles AS (
            SELECT DISTINCT ON (market_id)
                market_id,
                avg_spread_ticks,
                price_volatility,
                update_rate_per_min,
                avg_depth_best,
                total_matched_volume
            FROM market_profiles_daily
            ORDER BY market_id, profile_date DESC
        ),
        scored AS (
            SELECT
                es.total_score,
                lp.avg_spread_ticks,
                lp.price_volatility,
                lp.update_rate_per_min,
                lp.avg_depth_best,
                lp.total_matched_volume,
                CASE
                    WHEN es.total_score >= 70 THEN 'Excellent (70+)'
                    WHEN es.total_score >= 55 THEN 'High (55-70)'
                    WHEN es.total_score >= 40 THEN 'Medium (40-55)'
                    ELSE 'Low (<40)'
                END AS band
            FROM exploitability_scores es
            JOIN markets m ON es.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            JOIN latest_profiles lp ON es.market_id = lp.market_id
            WHERE c.enabled = true
        )
        SELECT
            band,
            COUNT(*) AS count,
            ROUND(AVG(avg_spread_ticks)::numeric, 2) AS avg_spread_ticks,
            ROUND(MIN(avg_spread_ticks)::numeric, 2) AS min_spread,
            ROUND(MAX(avg_spread_ticks)::numeric, 2) AS max_spread,
            ROUND(AVG(price_volatility)::numeric, 4) AS avg_volatility,
            ROUND(AVG(update_rate_per_min)::numeric, 2) AS avg_update_rate,
            ROUND(AVG(avg_depth_best)::numeric, 0) AS avg_depth,
            ROUND(AVG(total_matched_volume)::numeric, 0) AS avg_volume,
            ROUND(MIN(total_matched_volume)::numeric, 0) AS min_volume,
            ROUND(MAX(total_matched_volume)::numeric, 0) AS max_volume
        FROM scored
        GROUP BY band
        ORDER BY
            CASE band
                WHEN 'Excellent (70+)' THEN 1
                WHEN 'High (55-70)' THEN 2
                WHEN 'Medium (40-55)' THEN 3
                ELSE 4
            END
    """)

    result = await db.execute(query)
    rows = result.all()

    return [
        RawMetricStats(
            band=row.band,
            count=row.count,
            avg_spread_ticks=float(row.avg_spread_ticks or 0),
            min_spread=float(row.min_spread or 0),
            max_spread=float(row.max_spread or 0),
            avg_volatility=float(row.avg_volatility or 0),
            avg_update_rate=float(row.avg_update_rate or 0),
            avg_depth=float(row.avg_depth or 0),
            avg_volume=float(row.avg_volume or 0),
            min_volume=float(row.min_volume or 0),
            max_volume=float(row.max_volume or 0),
        )
        for row in rows
    ]


@router.get("/competition-leaderboard", response_model=list[CompetitionRanking])
async def get_competition_leaderboard(
    db: AsyncSession = Depends(get_db),
    min_markets: int = Query(5, description="Minimum markets scored"),
    limit: int = Query(25, ge=1, le=50),
):
    """
    Get competition leaderboard.

    Which competitions produce the best scores? This is LEARNED from data.
    """
    # Use latest profile per market for robustness
    query = text("""
        WITH latest_profiles AS (
            SELECT DISTINCT ON (market_id)
                market_id,
                avg_spread_ticks,
                total_matched_volume
            FROM market_profiles_daily
            ORDER BY market_id, profile_date DESC
        )
        SELECT
            c.name AS name,
            c.country_code,
            COUNT(DISTINCT es.market_id) AS markets_scored,
            ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
            ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
            COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value_markets,
            COUNT(*) FILTER (WHERE es.total_score >= 70) AS excellent_markets,
            ROUND(AVG(lp.avg_spread_ticks)::numeric, 2) AS avg_spread,
            ROUND(AVG(lp.total_matched_volume)::numeric, 0) AS avg_volume
        FROM exploitability_scores es
        JOIN markets m ON es.market_id = m.id
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        LEFT JOIN latest_profiles lp ON es.market_id = lp.market_id
        WHERE c.enabled = true
        GROUP BY c.id, c.name, c.country_code
        HAVING COUNT(DISTINCT es.market_id) >= :min_markets
        ORDER BY AVG(es.total_score) DESC
        LIMIT :limit
    """)

    result = await db.execute(query, {"min_markets": min_markets, "limit": limit})
    rows = result.all()

    return [
        CompetitionRanking(
            name=row.name,
            country_code=row.country_code,
            markets_scored=row.markets_scored,
            avg_score=float(row.avg_score or 0),
            max_score=float(row.max_score or 0),
            high_value_markets=row.high_value_markets or 0,
            excellent_markets=row.excellent_markets or 0,
            avg_spread=float(row.avg_spread or 0),
            avg_volume=float(row.avg_volume or 0),
        )
        for row in rows
    ]


@router.get("/time-buckets", response_model=list[TimeBucketStats])
async def get_time_bucket_stats(db: AsyncSession = Depends(get_db)):
    """
    Get statistics by time bucket.

    Which time windows produce the best scores?
    """
    query = text("""
        SELECT
            es.time_bucket AS bucket,
            COUNT(*) AS total_scores,
            ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
            ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
            COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value,
            COUNT(*) FILTER (WHERE es.total_score >= 70) AS excellent,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE es.total_score >= 55) / NULLIF(COUNT(*), 0),
                2
            ) AS pct_high_value
        FROM exploitability_scores es
        JOIN markets m ON es.market_id = m.id
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        WHERE c.enabled = true
        GROUP BY es.time_bucket
        ORDER BY
            CASE es.time_bucket
                WHEN '72h+' THEN 1
                WHEN '24-72h' THEN 2
                WHEN '6-24h' THEN 3
                WHEN '2-6h' THEN 4
                WHEN '<2h' THEN 5
                ELSE 6
            END
    """)

    result = await db.execute(query)
    rows = result.all()

    return [
        TimeBucketStats(
            bucket=row.bucket,
            total_scores=row.total_scores,
            avg_score=float(row.avg_score or 0),
            max_score=float(row.max_score or 0),
            high_value=row.high_value or 0,
            excellent=row.excellent or 0,
            pct_high_value=float(row.pct_high_value or 0),
        )
        for row in rows
    ]


@router.get("/odds-bands", response_model=list[OddsBandStats])
async def get_odds_band_stats(db: AsyncSession = Depends(get_db)):
    """
    Get statistics by odds band.

    Which odds ranges produce the best scores?
    """
    query = text("""
        SELECT
            es.odds_band AS band,
            COUNT(*) AS total_scores,
            ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
            ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
            COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE es.total_score >= 55) / NULLIF(COUNT(*), 0),
                2
            ) AS pct_high_value
        FROM exploitability_scores es
        JOIN markets m ON es.market_id = m.id
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        WHERE c.enabled = true
        GROUP BY es.odds_band
        ORDER BY AVG(es.total_score) DESC
    """)

    result = await db.execute(query)
    rows = result.all()

    return [
        OddsBandStats(
            band=row.band,
            total_scores=row.total_scores,
            avg_score=float(row.avg_score or 0),
            max_score=float(row.max_score or 0),
            high_value=row.high_value or 0,
            pct_high_value=float(row.pct_high_value or 0),
        )
        for row in rows
    ]


@router.get("/volume-analysis", response_model=list[VolumeBandStats])
async def get_volume_analysis(db: AsyncSession = Depends(get_db)):
    """
    Get volume penalty effectiveness analysis.

    Verify that high-volume markets are scoring low.
    """
    # Use CTE with latest profile per market
    query = text("""
        WITH latest_profiles AS (
            SELECT DISTINCT ON (market_id)
                market_id,
                total_matched_volume
            FROM market_profiles_daily
            ORDER BY market_id, profile_date DESC
        ),
        scored AS (
            SELECT
                es.total_score,
                es.volume_penalty,
                lp.total_matched_volume,
                CASE
                    WHEN lp.total_matched_volume > 200000 THEN 'Very High (>200k)'
                    WHEN lp.total_matched_volume > 100000 THEN 'High (100-200k)'
                    WHEN lp.total_matched_volume > 50000 THEN 'Medium (50-100k)'
                    WHEN lp.total_matched_volume > 30000 THEN 'Low-Med (30-50k)'
                    ELSE 'Low (<30k)'
                END AS band
            FROM exploitability_scores es
            JOIN markets m ON es.market_id = m.id
            JOIN events e ON m.event_id = e.id
            JOIN competitions c ON e.competition_id = c.id
            JOIN latest_profiles lp ON es.market_id = lp.market_id
            WHERE c.enabled = true
        )
        SELECT
            band,
            COUNT(*) AS market_count,
            ROUND(AVG(total_score)::numeric, 2) AS avg_score,
            ROUND(AVG(volume_penalty)::numeric, 2) AS avg_volume_penalty,
            COUNT(*) FILTER (WHERE total_score >= 55) AS high_value
        FROM scored
        GROUP BY band
        ORDER BY
            CASE band
                WHEN 'Low (<30k)' THEN 1
                WHEN 'Low-Med (30-50k)' THEN 2
                WHEN 'Medium (50-100k)' THEN 3
                WHEN 'High (100-200k)' THEN 4
                ELSE 5
            END
    """)

    result = await db.execute(query)
    rows = result.all()

    return [
        VolumeBandStats(
            band=row.band,
            market_count=row.market_count,
            avg_score=float(row.avg_score or 0),
            avg_volume_penalty=float(row.avg_volume_penalty or 0),
            high_value=row.high_value or 0,
        )
        for row in rows
    ]


@router.get("/high-scoring-markets", response_model=list[HighScoringMarket])
async def get_high_scoring_markets(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(55, description="Minimum score"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Get high scoring markets with full details.

    Shows the raw metrics for markets scoring above threshold.
    """
    # Subquery for latest scores
    latest_score_subq = (
        select(
            ExploitabilityScore.market_id,
            func.max(ExploitabilityScore.id).label("max_id")
        )
        .group_by(ExploitabilityScore.market_id)
        .subquery()
    )

    query = text("""
        WITH latest_scores AS (
            SELECT market_id, MAX(id) as max_id
            FROM exploitability_scores
            GROUP BY market_id
        ),
        latest_profiles AS (
            SELECT DISTINCT ON (market_id)
                market_id,
                avg_spread_ticks,
                price_volatility,
                avg_depth_best,
                total_matched_volume
            FROM market_profiles_daily
            ORDER BY market_id, profile_date DESC
        )
        SELECT
            c.name AS competition,
            e.name AS event,
            m.name AS market,
            es.total_score,
            es.time_bucket,
            es.odds_band,
            es.spread_score,
            es.volatility_score,
            es.update_score,
            es.depth_score,
            es.volume_penalty,
            lp.avg_spread_ticks,
            lp.price_volatility,
            lp.avg_depth_best,
            lp.total_matched_volume
        FROM exploitability_scores es
        JOIN latest_scores ls ON es.market_id = ls.market_id AND es.id = ls.max_id
        JOIN markets m ON es.market_id = m.id
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        LEFT JOIN latest_profiles lp ON es.market_id = lp.market_id
        WHERE es.total_score >= :min_score
          AND c.enabled = true
        ORDER BY es.total_score DESC
        LIMIT :limit
    """)

    result = await db.execute(query, {"min_score": min_score, "limit": limit})
    rows = result.all()

    return [
        HighScoringMarket(
            competition=row.competition,
            event=row.event,
            market=row.market,
            total_score=float(row.total_score),
            time_bucket=row.time_bucket,
            odds_band=row.odds_band,
            spread_score=float(row.spread_score or 0),
            volatility_score=float(row.volatility_score or 0),
            update_score=float(row.update_score or 0),
            depth_score=float(row.depth_score or 0),
            volume_penalty=float(row.volume_penalty or 0),
            avg_spread_ticks=float(row.avg_spread_ticks) if row.avg_spread_ticks else None,
            price_volatility=float(row.price_volatility) if row.price_volatility else None,
            avg_depth_best=float(row.avg_depth_best) if row.avg_depth_best else None,
            total_matched_volume=float(row.total_matched_volume) if row.total_matched_volume else None,
        )
        for row in rows
    ]


@router.get("/closing-data/summary", response_model=ClosingDataSummary)
async def get_closing_data_summary(db: AsyncSession = Depends(get_db)):
    """
    Get summary of captured closing data.

    Shows how many markets have final scores, closing odds, and results.
    This is CRITICAL for Phase 1 validation readiness.
    """
    query = text("""
        SELECT
            COUNT(*) AS total_captured,
            COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) AS with_closing_odds,
            COUNT(*) FILTER (WHERE final_score IS NOT NULL) AS with_final_score,
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS with_results,
            COUNT(*) FILTER (WHERE final_score >= 55) AS high_score_captured,
            COUNT(*) FILTER (WHERE final_score >= 70) AS excellent_score_captured
        FROM market_closing_data
    """)

    result = await db.execute(query)
    row = result.one()

    return ClosingDataSummary(
        total_captured=row.total_captured or 0,
        with_closing_odds=row.with_closing_odds or 0,
        with_final_score=row.with_final_score or 0,
        with_results=row.with_results or 0,
        high_score_captured=row.high_score_captured or 0,
        excellent_score_captured=row.excellent_score_captured or 0,
    )


@router.get("/closing-data/high-scores", response_model=list[ClosingDataItem])
async def get_closing_data_high_scores(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(55, description="Minimum final score"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Get closing data for high-scoring markets.

    Shows final scores, closing odds, and results for validation analysis.
    This is the key data for backtesting the strategy.
    """
    query = text("""
        SELECT
            mcd.market_id,
            c.name AS competition,
            e.name AS event,
            m.name AS market_name,
            mcd.final_score,
            mcd.closing_odds,
            mcd.result,
            mcd.minutes_to_start,
            mcd.odds_captured_at,
            mcd.settled_at
        FROM market_closing_data mcd
        JOIN markets m ON mcd.market_id = m.id
        JOIN events e ON m.event_id = e.id
        JOIN competitions c ON e.competition_id = c.id
        WHERE mcd.final_score >= :min_score
        ORDER BY mcd.final_score DESC
        LIMIT :limit
    """)

    result = await db.execute(query, {"min_score": min_score, "limit": limit})
    rows = result.all()

    items = []
    for row in rows:
        # Extract first runner's closing odds for display
        closing_back = None
        closing_lay = None
        if row.closing_odds and row.closing_odds.get("runners"):
            first_runner = row.closing_odds["runners"][0]
            closing_back = first_runner.get("back_price")
            closing_lay = first_runner.get("lay_price")

        # Extract winner name
        winner = None
        if row.result:
            winner = row.result.get("winner_name")

        items.append(ClosingDataItem(
            market_id=row.market_id,
            competition=row.competition,
            event=row.event,
            market_name=row.market_name,
            final_score=float(row.final_score) if row.final_score else None,
            closing_back_price=closing_back,
            closing_lay_price=closing_lay,
            winner=winner,
            minutes_to_start=row.minutes_to_start,
            odds_captured_at=row.odds_captured_at.isoformat() if row.odds_captured_at else None,
            settled_at=row.settled_at.isoformat() if row.settled_at else None,
        ))

    return items
