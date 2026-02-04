"""Exploitability scoring engine.

Calculates exploitability scores for markets based on structural characteristics.
Higher scores indicate markets with potential for exploitation.

CRITICAL DESIGN PRINCIPLE:
- High volume = PENALTY (market is efficient)
- We want moderate spread, volatility, and depth
- Too tight = efficient, too wide = illiquid
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog
import yaml
from pathlib import Path

logger = structlog.get_logger(__name__)


@dataclass
class MarketMetrics:
    """Input metrics for scoring calculation."""

    spread_ticks: float
    volatility: float
    update_rate: float
    depth: float
    volume: float

    # Optional context
    mean_price: float | None = None
    snapshot_count: int = 0


@dataclass
class ExploitabilityResult:
    """Result of exploitability calculation with component breakdown."""

    total_score: float
    spread_score: float
    volatility_score: float
    update_score: float
    depth_score: float
    volume_penalty: float

    # Raw inputs for debugging
    metrics: MarketMetrics | None = None

    # Guards triggered
    guards_failed: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "total_score": self.total_score,
            "spread_score": self.spread_score,
            "volatility_score": self.volatility_score,
            "update_score": self.update_score,
            "depth_score": self.depth_score,
            "volume_penalty": self.volume_penalty,
            "guards_failed": self.guards_failed,
        }


class ScoringEngine:
    """
    Calculate exploitability scores for markets.

    Formula:
    score = 100 × (
        w_spread × f_spread(spread)
      + w_volatility × f_volatility(volatility)
      + w_update × f_update(update_rate)
      + w_depth × f_depth(depth)
      - w_volume × f_volume(volume)
    )

    CRITICAL: High volume = PENALTY (market is efficient)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize scoring engine.

        Args:
            config: Optional scoring configuration. If not provided,
                   loads from defaults.yaml
        """
        if config is None:
            config = self._load_default_config()

        self.config = config
        self.weights = config.get("weights", {})
        self.normalisation = config.get("normalisation", {})
        self.guards = config.get("guards", {})

        # Validate configuration
        self._validate_config()

    def _load_default_config(self) -> dict[str, Any]:
        """Load scoring config from defaults.yaml."""
        config_path = Path(__file__).parent.parent.parent / "config" / "defaults.yaml"
        if config_path.exists():
            with open(config_path) as f:
                full_config = yaml.safe_load(f) or {}
                return full_config.get("scoring", {})
        return self._get_fallback_config()

    def _get_fallback_config(self) -> dict[str, Any]:
        """Fallback configuration if defaults.yaml not found."""
        return {
            "weights": {
                "spread": 0.25,
                "volatility": 0.25,
                "update_rate": 0.15,
                "depth": 0.20,
                "volume_penalty": 0.15,
            },
            "normalisation": {
                "spread": {"min_ticks": 2, "sweet_spot_max": 8, "max_ticks": 12},
                "volatility": {"target": 0.04, "max": 0.12},
                "update_rate": {"min": 0.2, "max": 3.0},
                "depth": {"min": 150, "optimal": 1500, "max": 8000},
                "volume": {"threshold": 30000, "max": 200000, "hard_cap": 500000},
            },
            "guards": {
                "absolute_min_depth": 100,
                "absolute_max_spread_ticks": 20,
                "min_snapshots_required": 5,
            },
        }

    def _validate_config(self) -> None:
        """Validate configuration has all required keys."""
        required_weights = ["spread", "volatility", "update_rate", "depth", "volume_penalty"]
        for w in required_weights:
            if w not in self.weights:
                raise ValueError(f"Missing weight: {w}")

    @staticmethod
    def clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value between min and max."""
        return max(min_val, min(value, max_val))

    def f_spread(self, spread_ticks: float) -> float:
        """
        Score spread in ticks.

        Moderate spread = exploitable.
        Too tight (1-2 ticks) = efficient, penalise.
        Too wide (12+ ticks) = illiquid, penalise.
        Sweet spot: 3-8 ticks.

        Returns value in [0, 1] where 1 = optimal.
        """
        params = self.normalisation.get("spread", {})
        min_ticks = params.get("min_ticks", 2)
        sweet_spot_max = params.get("sweet_spot_max", 8)
        max_ticks = params.get("max_ticks", 12)

        if spread_ticks < min_ticks:
            # Too tight = efficient
            return spread_ticks / min_ticks * 0.3  # Max 30% score
        elif spread_ticks <= sweet_spot_max:
            # Sweet spot - scale 0.3 to 1.0
            range_size = sweet_spot_max - min_ticks
            position = spread_ticks - min_ticks
            return 0.3 + (position / range_size) * 0.7
        else:
            # Too wide - decay from 1.0 to 0
            excess = spread_ticks - sweet_spot_max
            max_excess = max_ticks - sweet_spot_max
            return max(0, 1.0 - (excess / max_excess))

    def f_volatility(self, volatility: float) -> float:
        """
        Score price volatility.

        Bell curve around target volatility.
        Too low = no movement = no opportunity.
        Too high = chaos = risk.

        Returns value in [0, 1] where 1 = optimal.
        """
        params = self.normalisation.get("volatility", {})
        target = params.get("target", 0.04)
        max_vol = params.get("max", 0.12)

        if volatility <= 0:
            return 0

        if volatility < target:
            # Below target - linear scale up
            return volatility / target
        else:
            # Above target - decay
            excess = volatility - target
            max_excess = max_vol - target
            if max_excess <= 0:
                return 0
            return max(0, 1.0 - (excess / max_excess))

    def f_update(self, update_rate: float) -> float:
        """
        Score update rate (changes per minute).

        Higher = more active = better.
        Diminishing returns via log scale.

        Returns value in [0, 1].
        """
        params = self.normalisation.get("update_rate", {})
        min_rate = params.get("min", 0.2)
        max_rate = params.get("max", 3.0)

        if update_rate <= 0:
            return 0
        if update_rate < min_rate:
            return update_rate / min_rate * 0.3  # Max 30% for very low rates

        # Log scale for diminishing returns
        # log(1 + rate) / log(1 + max_rate)
        return self.clamp(
            math.log(1 + update_rate) / math.log(1 + max_rate),
            0,
            1,
        )

    def f_depth(self, depth: float) -> float:
        """
        Score market depth (liquidity at best prices).

        Need minimum to be tradeable.
        Optimal around £500-2000.
        Very high (£8k+) suggests efficient market.

        Returns value in [0, 1].
        """
        params = self.normalisation.get("depth", {})
        min_depth = params.get("min", 150)
        optimal = params.get("optimal", 1500)
        max_depth = params.get("max", 8000)

        if depth < min_depth:
            return 0  # Below minimum = unusable

        if depth <= optimal:
            # Scale from min to optimal
            return (depth - min_depth) / (optimal - min_depth)
        else:
            # Above optimal - slight decay (efficient market)
            excess = depth - optimal
            max_excess = max_depth - optimal
            if max_excess <= 0:
                return 1.0
            # Decay from 1.0 to 0.7 as depth increases
            return max(0.7, 1.0 - (excess / max_excess) * 0.3)

    def f_volume(self, volume: float) -> float:
        """
        PENALTY function for matched volume.

        CRITICAL: High volume = efficient market = BAD for us.

        Below threshold = no penalty (returns 0).
        Above threshold = increasing penalty.
        Above hard cap = maximum penalty (returns 1).

        Returns penalty value in [0, 1].
        """
        params = self.normalisation.get("volume", {})
        threshold = params.get("threshold", 30000)
        max_vol = params.get("max", 200000)
        hard_cap = params.get("hard_cap", 500000)

        if volume <= threshold:
            return 0  # No penalty for low volume

        if volume >= hard_cap:
            return 1.0  # Maximum penalty

        # Linear scale between threshold and max
        excess = volume - threshold
        max_excess = max_vol - threshold
        if max_excess <= 0:
            return 1.0

        return self.clamp(excess / max_excess, 0, 1)

    def check_guards(self, metrics: MarketMetrics) -> list[str]:
        """
        Check if metrics pass guard thresholds.

        Returns list of failed guard names (empty = all passed).
        """
        failed = []

        min_depth = self.guards.get("absolute_min_depth", 100)
        if metrics.depth < min_depth:
            failed.append(f"depth_below_{min_depth}")

        max_spread = self.guards.get("absolute_max_spread_ticks", 20)
        if metrics.spread_ticks > max_spread:
            failed.append(f"spread_above_{max_spread}")

        min_snapshots = self.guards.get("min_snapshots_required", 5)
        if metrics.snapshot_count < min_snapshots:
            failed.append(f"snapshots_below_{min_snapshots}")

        # Volume hard cap check
        volume_params = self.normalisation.get("volume", {})
        hard_cap = volume_params.get("hard_cap", 500000)
        if metrics.volume > hard_cap:
            failed.append(f"volume_above_{hard_cap}")

        return failed

    def calculate_score(self, metrics: MarketMetrics) -> ExploitabilityResult:
        """
        Calculate exploitability score with component breakdown.

        Args:
            metrics: Input market metrics

        Returns:
            ExploitabilityResult with total score and components
        """
        # Check guards first
        guards_failed = self.check_guards(metrics)
        if guards_failed:
            logger.debug(
                "guards_failed",
                guards=guards_failed,
                spread=metrics.spread_ticks,
                depth=metrics.depth,
                volume=metrics.volume,
            )
            return ExploitabilityResult(
                total_score=0,
                spread_score=0,
                volatility_score=0,
                update_score=0,
                depth_score=0,
                volume_penalty=0,
                metrics=metrics,
                guards_failed=guards_failed,
            )

        # Calculate component scores (all in [0, 1])
        spread_norm = self.f_spread(metrics.spread_ticks)
        volatility_norm = self.f_volatility(metrics.volatility)
        update_norm = self.f_update(metrics.update_rate)
        depth_norm = self.f_depth(metrics.depth)
        volume_penalty_norm = self.f_volume(metrics.volume)

        # Get weights
        w_spread = self.weights.get("spread", 0.25)
        w_volatility = self.weights.get("volatility", 0.25)
        w_update = self.weights.get("update_rate", 0.15)
        w_depth = self.weights.get("depth", 0.20)
        w_volume = self.weights.get("volume_penalty", 0.15)

        # Calculate weighted score
        # Note: volume_penalty is SUBTRACTED
        raw_score = (
            w_spread * spread_norm
            + w_volatility * volatility_norm
            + w_update * update_norm
            + w_depth * depth_norm
            - w_volume * volume_penalty_norm
        )

        # Scale to 0-100
        total_score = self.clamp(raw_score * 100, 0, 100)

        # Scale component scores to 0-100 for reporting
        result = ExploitabilityResult(
            total_score=round(total_score, 2),
            spread_score=round(spread_norm * 100, 2),
            volatility_score=round(volatility_norm * 100, 2),
            update_score=round(update_norm * 100, 2),
            depth_score=round(depth_norm * 100, 2),
            volume_penalty=round(volume_penalty_norm * 100, 2),
            metrics=metrics,
            guards_failed=None,
        )

        logger.debug(
            "score_calculated",
            total=result.total_score,
            spread=result.spread_score,
            volatility=result.volatility_score,
            update=result.update_score,
            depth=result.depth_score,
            volume_penalty=result.volume_penalty,
        )

        return result


# Convenience function for testing
def score_market(
    spread_ticks: float,
    volatility: float,
    update_rate: float,
    depth: float,
    volume: float,
    snapshot_count: int = 10,
) -> ExploitabilityResult:
    """
    Quick scoring function for testing.

    Args:
        spread_ticks: Spread in tick increments
        volatility: Price volatility
        update_rate: Updates per minute
        depth: Liquidity at best prices
        volume: Total matched volume
        snapshot_count: Number of snapshots collected

    Returns:
        ExploitabilityResult
    """
    engine = ScoringEngine()
    metrics = MarketMetrics(
        spread_ticks=spread_ticks,
        volatility=volatility,
        update_rate=update_rate,
        depth=depth,
        volume=volume,
        snapshot_count=snapshot_count,
    )
    return engine.calculate_score(metrics)
