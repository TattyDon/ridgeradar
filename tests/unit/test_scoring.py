"""Unit tests for the scoring engine.

CRITICAL TESTS:
- High volume markets (EPL-like) MUST score LOW
- Secondary league markets MUST score HIGHER
- Illiquid markets MUST score LOW due to depth guards

These tests validate the core business logic of RidgeRadar.
"""

import pytest

from app.services.scoring.engine import MarketMetrics, ScoringEngine, score_market


class TestScoringEngine:
    """Test the ScoringEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ScoringEngine()

    def test_engine_initialization(self):
        """Test engine initializes with configuration."""
        assert self.engine.weights is not None
        assert "spread" in self.engine.weights
        assert "volatility" in self.engine.weights
        assert "volume_penalty" in self.engine.weights

    def test_high_volume_market_scores_low(self):
        """
        Premier League-like market should score low due to volume penalty.

        These markets have:
        - Very tight spreads (efficient)
        - Low volatility (stable)
        - High update rate (active)
        - Deep liquidity
        - HIGH VOLUME (the killer)
        """
        profile = MarketMetrics(
            spread_ticks=1,       # Very tight
            volatility=0.015,     # Very stable
            update_rate=4.0,      # Very active
            depth=12000,          # Very deep
            volume=450000,        # Very high volume - PENALTY
            snapshot_count=100,
        )
        result = self.engine.calculate_score(profile)

        # Should be unattractive due to volume penalty
        assert result.total_score < 40, (
            f"High volume market scored {result.total_score}, expected < 40. "
            f"Volume penalty was only {result.volume_penalty}"
        )

    def test_secondary_league_market_scores_high(self):
        """
        2. Bundesliga-like market should score higher.

        These markets have:
        - Moderate spread (exploitable)
        - Good volatility (opportunity)
        - Moderate activity
        - Adequate depth
        - LOW volume (good for us)
        """
        profile = MarketMetrics(
            spread_ticks=5,       # Moderate spread
            volatility=0.045,     # Good volatility
            update_rate=0.8,      # Moderate activity
            depth=620,            # Adequate depth
            volume=18000,         # Low volume - no penalty
            snapshot_count=50,
        )
        result = self.engine.calculate_score(profile)

        # Should be interesting (score above 50 indicates opportunity)
        assert result.total_score > 50, (
            f"Secondary league market scored {result.total_score}, expected > 50"
        )

    def test_illiquid_market_scores_low(self):
        """
        Very thin market should score low due to depth guard.

        Can't trade if there's no liquidity.
        """
        profile = MarketMetrics(
            spread_ticks=8,
            volatility=0.09,
            update_rate=0.05,     # Nearly stale
            depth=50,             # Below minimum!
            volume=1000,
            snapshot_count=10,
        )
        result = self.engine.calculate_score(profile)

        # Should fail depth guard
        assert result.total_score == 0, (
            f"Illiquid market scored {result.total_score}, expected 0 (guard failure)"
        )
        assert result.guards_failed is not None
        assert any("depth" in g for g in result.guards_failed)

    def test_wide_spread_market_scores_low(self):
        """Market with very wide spread should score low."""
        profile = MarketMetrics(
            spread_ticks=25,      # Way too wide
            volatility=0.05,
            update_rate=0.5,
            depth=500,
            volume=5000,
            snapshot_count=20,
        )
        result = self.engine.calculate_score(profile)

        # Should fail spread guard
        assert result.total_score == 0
        assert result.guards_failed is not None

    def test_volume_hard_cap_triggers_guard(self):
        """Volume above hard cap should trigger guard."""
        profile = MarketMetrics(
            spread_ticks=5,
            volatility=0.04,
            update_rate=1.0,
            depth=1000,
            volume=600000,        # Above hard cap (500k)
            snapshot_count=50,
        )
        result = self.engine.calculate_score(profile)

        assert result.total_score == 0
        assert result.guards_failed is not None
        assert any("volume" in g for g in result.guards_failed)

    def test_insufficient_snapshots_triggers_guard(self):
        """Market with too few snapshots should trigger guard."""
        profile = MarketMetrics(
            spread_ticks=5,
            volatility=0.04,
            update_rate=1.0,
            depth=1000,
            volume=10000,
            snapshot_count=2,     # Below minimum (5)
        )
        result = self.engine.calculate_score(profile)

        assert result.total_score == 0
        assert result.guards_failed is not None


class TestNormalisationFunctions:
    """Test individual normalisation functions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ScoringEngine()

    def test_f_spread_tight_spread_low_score(self):
        """Tight spread (1 tick) should score low - too efficient."""
        score = self.engine.f_spread(1)
        assert score < 0.3, f"1 tick spread scored {score}, expected < 0.3"

    def test_f_spread_sweet_spot_high_score(self):
        """Sweet spot spread (5 ticks) should score high."""
        score = self.engine.f_spread(5)
        assert score > 0.6, f"5 tick spread scored {score}, expected > 0.6"

    def test_f_spread_wide_spread_low_score(self):
        """Wide spread (15 ticks) should score low."""
        score = self.engine.f_spread(15)
        assert score < 0.3, f"15 tick spread scored {score}, expected < 0.3"

    def test_f_volatility_target_high_score(self):
        """Target volatility should score highest."""
        score = self.engine.f_volatility(0.04)  # Target
        assert score > 0.9, f"Target volatility scored {score}, expected > 0.9"

    def test_f_volatility_low_vol_low_score(self):
        """Low volatility should score low."""
        score = self.engine.f_volatility(0.01)
        assert score < 0.5, f"Low volatility scored {score}, expected < 0.5"

    def test_f_volatility_high_vol_low_score(self):
        """High volatility should score low."""
        score = self.engine.f_volatility(0.15)
        assert score < 0.3, f"High volatility scored {score}, expected < 0.3"

    def test_f_depth_below_min_zero(self):
        """Depth below minimum should return 0."""
        score = self.engine.f_depth(50)
        assert score == 0, f"Below minimum depth scored {score}, expected 0"

    def test_f_depth_optimal_high_score(self):
        """Optimal depth should score high."""
        score = self.engine.f_depth(1500)  # Optimal
        assert score > 0.9, f"Optimal depth scored {score}, expected > 0.9"

    def test_f_volume_below_threshold_no_penalty(self):
        """Volume below threshold should have no penalty."""
        penalty = self.engine.f_volume(20000)
        assert penalty == 0, f"Low volume had penalty {penalty}, expected 0"

    def test_f_volume_above_threshold_has_penalty(self):
        """Volume above threshold should have penalty."""
        penalty = self.engine.f_volume(100000)
        assert penalty > 0, f"High volume had no penalty"

    def test_f_volume_at_max_full_penalty(self):
        """Volume at max should have full penalty."""
        penalty = self.engine.f_volume(200000)
        assert penalty >= 0.9, f"Max volume had penalty {penalty}, expected >= 0.9"


class TestScoreMarketHelper:
    """Test the convenience score_market function."""

    def test_score_market_returns_result(self):
        """Test the helper function returns expected structure."""
        result = score_market(
            spread_ticks=5,
            volatility=0.04,
            update_rate=1.0,
            depth=1000,
            volume=15000,
        )

        assert hasattr(result, "total_score")
        assert hasattr(result, "spread_score")
        assert hasattr(result, "volume_penalty")
        assert result.total_score >= 0
        assert result.total_score <= 100

    def test_score_market_different_inputs(self):
        """Different inputs should produce different scores."""
        result1 = score_market(
            spread_ticks=5,
            volatility=0.04,
            update_rate=1.0,
            depth=1000,
            volume=15000,
        )
        result2 = score_market(
            spread_ticks=2,
            volatility=0.01,
            update_rate=0.2,
            depth=500,
            volume=200000,
        )

        assert result1.total_score != result2.total_score


class TestScoringEdgeCases:
    """Test edge cases in scoring."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = ScoringEngine()

    def test_zero_volatility(self):
        """Zero volatility should return 0 score for that component."""
        score = self.engine.f_volatility(0)
        assert score == 0

    def test_zero_update_rate(self):
        """Zero update rate should return 0 score for that component."""
        score = self.engine.f_update(0)
        assert score == 0

    def test_negative_values_handled(self):
        """Negative values should be handled gracefully."""
        profile = MarketMetrics(
            spread_ticks=-5,
            volatility=-0.04,
            update_rate=-1.0,
            depth=-1000,
            volume=-15000,
            snapshot_count=10,
        )
        # Should not raise exception
        result = self.engine.calculate_score(profile)
        assert result.total_score >= 0

    def test_very_large_values(self):
        """Very large values should be handled."""
        profile = MarketMetrics(
            spread_ticks=1000,
            volatility=10.0,
            update_rate=1000.0,
            depth=10000000,
            volume=100000000,
            snapshot_count=1000,
        )
        result = self.engine.calculate_score(profile)
        # Should trigger guards or cap at reasonable values
        assert result.total_score <= 100
