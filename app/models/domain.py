"""Domain models for RidgeRadar.

This module defines all database models for the Betfair market analytics system.
The tier system is CRITICAL - it ensures we focus on secondary leagues and
NEVER ingest Premier League or other highly efficient markets.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Sport(Base, TimestampMixin):
    """
    Top-level sport category (Soccer, Tennis, etc.).

    Sports are permanent reference data from Betfair.
    """

    __tablename__ = "sports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    betfair_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    competitions: Mapped[list["Competition"]] = relationship(
        "Competition", back_populates="sport"
    )

    def __repr__(self) -> str:
        return f"<Sport {self.name} ({self.betfair_id})>"


class Competition(Base, TimestampMixin):
    """
    League/tournament within a sport.

    Philosophy: We ingest ALL competitions and let the scoring engine filter.
    The tier field is now mainly for hard exclusions (friendlies, youth, etc.)
    rather than pre-judging market efficiency.

    The enabled field controls whether we capture data for this competition.
    CompetitionStats tracks learned efficiency patterns over time.
    """

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    betfair_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    sport_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sports.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        doc="'active' or 'excluded' - only for hard exclusions (friendlies, youth)",
    )

    # Relationships
    sport: Mapped["Sport"] = relationship("Sport", back_populates="competitions")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="competition")
    stats: Mapped[list["CompetitionStats"]] = relationship(
        "CompetitionStats", back_populates="competition"
    )

    __table_args__ = (
        Index("idx_competitions_tier", "tier", postgresql_where=(enabled == True)),
    )

    def __repr__(self) -> str:
        return f"<Competition {self.name} (enabled={self.enabled})>"


class Event(Base, TimestampMixin):
    """
    Single match/game.

    Events are linked to competitions and inherit their tier.
    Only events from non-excluded competitions should be stored.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    betfair_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    competition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("competitions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED")

    # Relationships
    competition: Mapped["Competition"] = relationship(
        "Competition", back_populates="events"
    )
    markets: Mapped[list["Market"]] = relationship("Market", back_populates="event")

    __table_args__ = (
        Index(
            "idx_events_scheduled",
            "scheduled_start",
            postgresql_where=(status == "SCHEDULED"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Event {self.name} ({self.scheduled_start})>"


class EventResult(Base):
    """
    Actual match outcome and statistics.

    CRITICAL for Phase 2+ validation:
    - Over/Under markets need actual goals to validate
    - Correct Score markets need exact scoreline
    - HT/FT markets need half-time and full-time scores
    - General statistics help understand market efficiency

    Without this data, we cannot properly validate:
    1. Whether high-scoring O/U 2.5 markets actually had edge
    2. CLV analysis for different market types
    3. Sport-specific pattern analysis
    """

    __tablename__ = "event_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id"), nullable=False, unique=True
    )

    # Core result (applicable to all sports)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING",
        doc="PENDING, COMPLETED, ABANDONED, POSTPONED"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Football-specific scores
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_ht_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Half-time home score"
    )
    away_ht_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Half-time away score"
    )

    # Derived values (computed on insert for easy querying)
    total_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    btts: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, doc="Both Teams To Score"
    )

    # Tennis-specific (sets won)
    home_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Extended statistics (JSONB for flexibility)
    statistics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        doc="""
        Sport-specific stats. Examples:
        Football: {"corners": [5, 3], "cards": [2, 1], "shots": [12, 8]}
        Tennis: {"set_scores": ["6-4", "3-6", "7-5"], "aces": [8, 5]}
        """
    )

    # Metadata
    source: Mapped[str | None] = mapped_column(
        String(50), nullable=True, doc="Data source: betfair, api-football, manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event")

    __table_args__ = (
        Index("idx_event_results_status", "status"),
        Index("idx_event_results_total_goals", "total_goals", postgresql_where=(total_goals.isnot(None))),
    )

    def __repr__(self) -> str:
        if self.home_score is not None:
            return f"<EventResult {self.event_id}: {self.home_score}-{self.away_score}>"
        return f"<EventResult {self.event_id}: {self.status}>"


class Market(Base, TimestampMixin):
    """
    Betting market within an event.

    Markets are where the actual trading happens. We capture snapshots
    of market state to build profiles and calculate exploitability scores.
    """

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    betfair_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    market_type: Mapped[str] = mapped_column(String(50), nullable=False)
    total_matched: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), default=Decimal("0.00")
    )
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    in_play: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="markets")
    runners: Mapped[list["Runner"]] = relationship("Runner", back_populates="market")
    snapshots: Mapped[list["MarketSnapshot"]] = relationship(
        "MarketSnapshot", back_populates="market"
    )
    profiles: Mapped[list["MarketProfileDaily"]] = relationship(
        "MarketProfileDaily", back_populates="market"
    )
    scores: Mapped[list["ExploitabilityScore"]] = relationship(
        "ExploitabilityScore",
        back_populates="market",
        foreign_keys="ExploitabilityScore.market_id",
    )

    __table_args__ = (Index("idx_markets_status", "status", "event_id"),)

    def __repr__(self) -> str:
        return f"<Market {self.name} ({self.market_type})>"


class Runner(Base):
    """
    Selection within a market (team, player, outcome).

    Runners are the actual things you can back or lay.
    """

    __tablename__ = "runners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    betfair_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")

    # Relationships
    market: Mapped["Market"] = relationship("Market", back_populates="runners")
    scores: Mapped[list["ExploitabilityScore"]] = relationship(
        "ExploitabilityScore", back_populates="runner"
    )

    __table_args__ = (
        UniqueConstraint("betfair_id", "market_id", name="uq_runner_market"),
    )

    def __repr__(self) -> str:
        return f"<Runner {self.name} ({self.betfair_id})>"


class MarketSnapshot(Base):
    """
    Point-in-time capture of market state.

    This is the raw data we collect every 60 seconds for active markets.
    The ladder_data JSONB contains the full price ladder for all runners.

    ladder_data format:
    {
        "runners": [
            {
                "runner_id": 12345,
                "last_traded": 2.50,
                "total_matched": 8420.50,
                "back": [
                    {"price": 2.44, "size": 320.00},
                    {"price": 2.42, "size": 580.00},
                    {"price": 2.40, "size": 450.00}
                ],
                "lay": [
                    {"price": 2.54, "size": 280.00},
                    {"price": 2.56, "size": 420.00},
                    {"price": 2.58, "size": 350.00}
                ]
            }
        ],
        "overround": 1.0456,
        "total_available": 4200.00
    }
    """

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    total_matched: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    total_available: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    overround: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    ladder_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Relationships
    market: Mapped["Market"] = relationship("Market", back_populates="snapshots")

    __table_args__ = (
        Index("idx_snapshots_market_time", "market_id", captured_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<MarketSnapshot market={self.market_id} at={self.captured_at}>"


class MarketProfileDaily(Base):
    """
    Aggregated daily metrics per market per time bucket.

    Profiles are computed from snapshots and provide the inputs
    for the exploitability scoring engine.

    Time buckets: '72h+', '24-72h', '6-24h', '2-6h', '<2h'
    """

    __tablename__ = "market_profiles_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    profile_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_bucket: Mapped[str] = mapped_column(String(20), nullable=False)

    # Spread metrics
    avg_spread_ticks: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    spread_volatility: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True
    )

    # Depth metrics
    avg_depth_best: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    depth_5_ticks: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Volume metrics
    total_matched_volume: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )

    # Activity metrics
    update_rate_per_min: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True
    )

    # Price metrics
    price_volatility: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6), nullable=True
    )
    mean_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Data quality
    snapshot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    market: Mapped["Market"] = relationship("Market", back_populates="profiles")

    __table_args__ = (
        UniqueConstraint(
            "market_id", "profile_date", "time_bucket", name="uq_profile_market_date_bucket"
        ),
    )

    def __repr__(self) -> str:
        return f"<MarketProfileDaily market={self.market_id} date={self.profile_date} bucket={self.time_bucket}>"


class ExploitabilityScore(Base):
    """
    Calculated exploitability score with component breakdown.

    This is the core output of the system. Higher scores indicate
    markets with structural inefficiencies that may be exploitable.

    CRITICAL: High volume markets should score LOW due to volume_penalty.
    Premier League matches should NEVER appear here (excluded tier).
    """

    __tablename__ = "exploitability_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    runner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("runners.id"), nullable=True
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    time_bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    odds_band: Mapped[str] = mapped_column(String(20), nullable=False)

    # Component scores (0-100 each)
    spread_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    volatility_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    update_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    depth_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    volume_penalty: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Final weighted score
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    # Config version used for reproducibility
    config_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("config_versions.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    market: Mapped["Market"] = relationship(
        "Market", back_populates="scores", foreign_keys=[market_id]
    )
    runner: Mapped["Runner | None"] = relationship("Runner", back_populates="scores")
    config_version: Mapped["ConfigVersion | None"] = relationship("ConfigVersion")

    __table_args__ = (
        Index(
            "idx_scores_total",
            total_score.desc(),
            postgresql_where=(total_score > 50),
        ),
        Index("idx_scores_market_time", "market_id", scored_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<ExploitabilityScore market={self.market_id} score={self.total_score}>"


class ConfigVersion(Base):
    """
    Configuration version history.

    All scoring configurations are versioned so we can:
    1. Reproduce past results
    2. A/B test different configurations
    3. Roll back changes if needed
    """

    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_type: Mapped[str] = mapped_column(
        String(50), nullable=False, doc="'scoring', 'global', 'universe'"
    )
    config_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<ConfigVersion {self.config_type} v{self.id} active={self.is_active}>"


class CompetitionStats(Base):
    """
    Aggregated statistics for competitions.

    This is LEARNED from market scores, not pre-configured.
    Used to:
    1. Identify which competitions consistently produce high-scoring markets
    2. Adjust snapshot frequency (more for high-value, less for low-value)
    3. Provide insights into market efficiency by competition
    """

    __tablename__ = "competition_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("competitions.id"), nullable=False
    )
    stats_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Score statistics
    markets_scored: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    min_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    score_std_dev: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Volume statistics (for understanding efficiency)
    avg_volume: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    total_volume: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    # Spread statistics
    avg_spread_ticks: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Count of markets above thresholds
    markets_above_40: Mapped[int] = mapped_column(Integer, default=0)
    markets_above_55: Mapped[int] = mapped_column(Integer, default=0)
    markets_above_70: Mapped[int] = mapped_column(Integer, default=0)

    # Rolling averages (updated periodically)
    rolling_30d_avg_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    competition: Mapped["Competition"] = relationship(back_populates="stats")

    __table_args__ = (
        Index("idx_competition_stats_date", "competition_id", "stats_date"),
        {"schema": None},
    )

    def __repr__(self) -> str:
        return f"<CompetitionStats {self.competition_id} {self.stats_date} avg={self.avg_score}>"


class MarketClosingData(Base):
    """
    Final state capture for market validation.

    This is CRITICAL for Phase 1 analysis. We capture:
    1. Final exploitability score before market goes in-play
    2. Closing odds for each runner (the "fair price" benchmark)
    3. Settlement result (for P&L calculation)

    Without this data, we cannot validate the scoring strategy.
    """

    __tablename__ = "market_closing_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False, unique=True
    )

    # Final score capture (before market goes in-play)
    final_score_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("exploitability_scores.id"), nullable=True
    )
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    score_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Closing odds snapshot (last prices before event starts)
    closing_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("market_snapshots.id"), nullable=True
    )
    closing_odds: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        doc="""
        Format: {
            "captured_at": "2024-01-15T14:58:00Z",
            "runners": [
                {
                    "runner_id": 12345,
                    "name": "Team A",
                    "back_price": 2.50,
                    "lay_price": 2.54,
                    "last_traded": 2.52,
                    "total_matched": 45000.00
                }
            ],
            "total_matched": 120000.00
        }
        """
    )
    odds_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    minutes_to_start: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        doc="Minutes before event start when closing odds captured"
    )

    # Settlement result (captured after event ends)
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        doc="""
        Format: {
            "winner_runner_id": 12345,
            "winner_name": "Team A",
            "runners": [
                {"runner_id": 12345, "status": "WINNER"},
                {"runner_id": 12346, "status": "LOSER"},
                {"runner_id": 12347, "status": "LOSER"}
            ]
        }
        """
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    market: Mapped["Market"] = relationship("Market")
    final_score_record: Mapped["ExploitabilityScore | None"] = relationship(
        "ExploitabilityScore", foreign_keys=[final_score_id]
    )
    closing_snapshot: Mapped["MarketSnapshot | None"] = relationship(
        "MarketSnapshot", foreign_keys=[closing_snapshot_id]
    )

    __table_args__ = (
        Index("idx_closing_data_score", "final_score", postgresql_where=(final_score.isnot(None))),
        Index("idx_closing_data_unsettled", "market_id", postgresql_where=(settled_at.is_(None))),
    )

    def __repr__(self) -> str:
        return f"<MarketClosingData market={self.market_id} score={self.final_score} settled={self.settled_at is not None}>"


class ShadowDecision(Base):
    """
    Hypothetical trading decision for Phase 2 validation.

    This is the CORE of Phase 2 shadow trading. Every time the system
    would trigger a trade, we log it here WITHOUT actually placing the bet.

    After 500+ decisions per niche, we can calculate:
    1. Theoretical ROI (did our selections win?)
    2. CLV (Closing Line Value) - were we getting good prices?
    3. Edge decay - is the edge stable over time?
    4. Cost-adjusted P&L - would we have profited after costs?

    Strategy Document Reference:
    - Phase 2 requires 2,000+ total shadow decisions
    - Need 500+ decisions per candidate niche
    - Must track to settlement and calculate realistic P&L
    """

    __tablename__ = "shadow_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # What we would have bet on
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id"), nullable=False
    )
    runner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runners.id"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(
        String(10), nullable=False, doc="BACK or LAY"
    )

    # Why we would have bet (the trigger)
    score_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exploitability_scores.id"), nullable=False
    )
    trigger_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, doc="Score that triggered this decision"
    )
    trigger_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="e.g. 'Score 72 > threshold 55, O/U 2.5 market'"
    )

    # Entry conditions at decision time
    decision_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    minutes_to_start: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_back_price: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, doc="Back price at decision time"
    )
    entry_lay_price: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, doc="Lay price at decision time"
    )
    entry_spread: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, doc="Spread at decision time"
    )
    available_to_back: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, doc="Volume available to back"
    )
    available_to_lay: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True, doc="Volume available to lay"
    )

    # Theoretical stake (what we would have bet)
    theoretical_stake: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=10.00,
        doc="Hypothetical stake for P&L calculation"
    )

    # Closing Line Value (captured later)
    closing_back_price: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, doc="Final back price before kickoff"
    )
    closing_lay_price: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, doc="Final lay price before kickoff"
    )
    clv_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4), nullable=True,
        doc="CLV = (closing_price - entry_price) / entry_price for backs"
    )

    # Outcome (captured after settlement)
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="WIN, LOSE, VOID, PENDING"
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # P&L calculation (after settlement)
    gross_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, doc="P&L before costs"
    )
    commission: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, doc="Estimated commission"
    )
    spread_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, doc="Cost of crossing spread"
    )
    net_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, doc="P&L after all costs"
    )

    # Niche classification (for aggregation)
    niche: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        doc="e.g. 'german_2_bundesliga_match_odds', 'spanish_segunda_over_under'"
    )
    competition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("competitions.id"), nullable=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    market: Mapped["Market"] = relationship("Market")
    runner: Mapped["Runner"] = relationship("Runner")
    score: Mapped["ExploitabilityScore"] = relationship("ExploitabilityScore")
    competition: Mapped["Competition | None"] = relationship("Competition")

    __table_args__ = (
        Index("idx_shadow_decisions_niche", "niche", "outcome"),
        Index("idx_shadow_decisions_pending", "market_id", postgresql_where=(outcome == "PENDING")),
        Index("idx_shadow_decisions_date", "decision_at"),
    )

    def __repr__(self) -> str:
        return f"<ShadowDecision {self.decision_type} on runner {self.runner_id} @ {self.entry_back_price}>"


class JobRun(Base):
    """
    Task execution audit log.

    Every scheduled task run is logged here for:
    1. Monitoring and alerting
    2. Debugging failures
    3. Performance tracking
    """

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, doc="'running', 'success', 'failed'"
    )
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    def __repr__(self) -> str:
        return f"<JobRun {self.job_name} status={self.status}>"
