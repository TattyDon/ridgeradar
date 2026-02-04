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
