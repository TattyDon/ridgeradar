"""Shadow Trading Configuration.

Defines all parameters for the Phase 2 shadow trading system.
This is PAPER TRADING only - no real money is ever at risk.

SAFETY: Phase 3 (live trading) requires explicit code changes
and will NEVER auto-activate.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class TradingPhase(str, Enum):
    """System trading phases."""
    PHASE1_COLLECTING = "PHASE1_COLLECTING"  # Gathering data
    PHASE2_SHADOW = "PHASE2_SHADOW"          # Paper trading
    PHASE3_LIVE = "PHASE3_LIVE"              # Real money (NOT IMPLEMENTED)


class DecisionStrategy(str, Enum):
    """Trading decision strategies."""
    BACK_BEST_VALUE = "back_best_value"      # Back runner with highest value signal
    BACK_FAVORITE = "back_favorite"          # Back the favorite
    BACK_UNDERDOG = "back_underdog"          # Back the underdog
    BACK_UNDER = "back_under"                # Back Under (O/U markets)
    BACK_OVER = "back_over"                  # Back Over (O/U markets)
    BACK_NO = "back_no"                      # Back No (BTTS markets)
    BACK_YES = "back_yes"                    # Back Yes (BTTS markets)
    LAY_FAVORITE = "lay_favorite"            # Lay the favorite
    SKIP = "skip"                            # Don't trade this market type


@dataclass
class MarketTypeRule:
    """Trading rules for a specific market type."""
    enabled: bool
    strategy: DecisionStrategy
    description: str
    runner_name_pattern: Optional[str] = None  # Regex to match runner name


@dataclass
class ActivationThresholds:
    """Thresholds required to activate shadow trading."""
    min_closing_data: int = 500
    min_results: int = 200
    min_high_score_markets: int = 50
    min_days_collecting: int = 2

    def check_ready(
        self,
        closing_data: int,
        results: int,
        high_score: int,
        days: int
    ) -> tuple[bool, dict]:
        """Check if thresholds are met. Returns (ready, details)."""
        details = {
            "closing_data": {
                "current": closing_data,
                "target": self.min_closing_data,
                "met": closing_data >= self.min_closing_data,
            },
            "results": {
                "current": results,
                "target": self.min_results,
                "met": results >= self.min_results,
            },
            "high_score_markets": {
                "current": high_score,
                "target": self.min_high_score_markets,
                "met": high_score >= self.min_high_score_markets,
            },
            "days_collecting": {
                "current": days,
                "target": self.min_days_collecting,
                "met": days >= self.min_days_collecting,
            },
        }
        ready = all(d["met"] for d in details.values())
        return ready, details


@dataclass
class EntryCriteria:
    """Criteria for entering a shadow trade.

    Time window: Strategy document specifies 6-24 hours before kickoff
    as the optimal window for detecting sharp money movement.
    """
    min_score: Decimal = Decimal("30")
    min_minutes_to_start: int = 360   # 6 hours - strategy optimal start
    max_minutes_to_start: int = 1440  # 24 hours - strategy optimal end
    min_total_matched: Decimal = Decimal("5000")
    max_spread_percent: Decimal = Decimal("5.0")
    market_status: str = "OPEN"
    require_not_in_play: bool = True


@dataclass
class StakeConfig:
    """Stake sizing configuration."""
    base_stake: Decimal = Decimal("10.00")
    use_kelly: bool = False
    kelly_fraction: Decimal = Decimal("0.25")
    max_stake_per_market: Decimal = Decimal("50.00")
    max_exposure_per_event: Decimal = Decimal("100.00")
    max_daily_exposure: Decimal = Decimal("500.00")
    commission_rate: Decimal = Decimal("0.02")  # 2% Betfair commission (discounted rate)


@dataclass
class ShadowTradingConfig:
    """Complete shadow trading configuration."""

    # System state
    enabled: bool = True
    auto_activate_phase2: bool = True

    # SAFETY: Live trading is NEVER auto-enabled
    live_trading_enabled: bool = False
    require_manual_live_activation: bool = True

    # Thresholds
    activation: ActivationThresholds = field(default_factory=ActivationThresholds)

    # Entry criteria
    entry: EntryCriteria = field(default_factory=EntryCriteria)

    # Stake sizing
    stake: StakeConfig = field(default_factory=StakeConfig)

    # Market type rules
    market_rules: dict[str, MarketTypeRule] = field(default_factory=lambda: {
        "MATCH_ODDS": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_BEST_VALUE,
            description="Back runner where score indicates mispricing",
        ),
        "OVER_UNDER_25": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_UNDER,
            description="Back Under 2.5 when score is high (less public action)",
            runner_name_pattern=r"Under 2\.5",
        ),
        "OVER_UNDER_15": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_UNDER,
            description="Back Under 1.5 when score is high",
            runner_name_pattern=r"Under 1\.5",
        ),
        "OVER_UNDER_35": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_UNDER,
            description="Back Under 3.5 when score is high",
            runner_name_pattern=r"Under 3\.5",
        ),
        "BOTH_TEAMS_TO_SCORE": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_NO,
            description="Back 'No' when score indicates value",
            runner_name_pattern=r"No",
        ),
        "DRAW_NO_BET": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_BEST_VALUE,
            description="Back runner with best value signal",
        ),
        "DOUBLE_CHANCE": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_BEST_VALUE,
            description="Back runner with best value signal",
        ),
        "HALF_TIME_FULL_TIME": MarketTypeRule(
            enabled=False,
            strategy=DecisionStrategy.SKIP,
            description="Skipped - too many selections, complex",
        ),
        "CORRECT_SCORE": MarketTypeRule(
            enabled=True,
            strategy=DecisionStrategy.BACK_BEST_VALUE,
            description="Tested via hypothesis engine (correct_score_value) with specific criteria",
        ),
        "ASIAN_HANDICAP": MarketTypeRule(
            enabled=False,
            strategy=DecisionStrategy.SKIP,
            description="Skipped - requires line selection logic",
        ),
    })

    def get_market_rule(self, market_type: str) -> MarketTypeRule:
        """Get the rule for a market type, with fallback to skip."""
        return self.market_rules.get(
            market_type,
            MarketTypeRule(
                enabled=False,
                strategy=DecisionStrategy.SKIP,
                description="Unknown market type - not traded",
            )
        )


# Global configuration instance
SHADOW_CONFIG = ShadowTradingConfig()


def get_shadow_config() -> ShadowTradingConfig:
    """Get the shadow trading configuration."""
    return SHADOW_CONFIG
