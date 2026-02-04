"""Unit tests for competition hard exclusion logic.

The new philosophy: Ingest broadly, filter by score.
- We no longer pre-judge leagues by name
- Hard exclusions are ONLY for things that waste API quota:
  - Friendlies
  - Youth/Reserve/Amateur matches
  - Wrong sports
- Everything else gets ingested and the scoring engine filters
"""

import pytest

from app.services.ingestion.discovery import should_exclude_competition


class TestHardExclusions:
    """Test that hard exclusions work for API-saving patterns."""

    def test_friendly_excluded(self):
        """Friendlies should be excluded to save API quota."""
        assert should_exclude_competition("International Friendly") is True
        assert should_exclude_competition("Club Friendly Games") is True
        assert should_exclude_competition("Friendly Match") is True

    def test_youth_competitions_excluded(self):
        """Youth competitions should be excluded."""
        assert should_exclude_competition("Premier League U21") is True
        assert should_exclude_competition("U19 European Championship") is True
        assert should_exclude_competition("U17 World Cup") is True

    def test_reserve_competitions_excluded(self):
        """Reserve leagues should be excluded."""
        assert should_exclude_competition("Premier League 2 (Reserves)") is True
        assert should_exclude_competition("La Liga Reserves") is True

    def test_amateur_competitions_excluded(self):
        """Amateur competitions should be excluded."""
        assert should_exclude_competition("Amateur League Division 1") is True

    def test_women_competitions_excluded(self):
        """Women's competitions excluded (different liquidity profile)."""
        assert should_exclude_competition("Women's World Cup") is True
        assert should_exclude_competition("NWSL Women") is True


class TestNoLongerExcluded:
    """
    Test that major leagues are NO LONGER excluded.

    Philosophy change: We ingest these and let the scoring engine
    penalise them due to high volume/tight spreads.
    """

    def test_premier_league_not_excluded(self):
        """
        EPL is now ingested - scoring engine will penalise it.

        High volume + tight spreads = low score automatically.
        """
        assert should_exclude_competition("English Premier League") is False
        assert should_exclude_competition("Premier League") is False

    def test_champions_league_not_excluded(self):
        """UCL is now ingested - scoring engine will penalise it."""
        assert should_exclude_competition("UEFA Champions League") is False
        assert should_exclude_competition("Champions League") is False

    def test_bundesliga_not_excluded(self):
        """Bundesliga is now ingested - scoring engine handles it."""
        assert should_exclude_competition("Bundesliga") is False
        assert should_exclude_competition("German Bundesliga") is False

    def test_la_liga_not_excluded(self):
        """La Liga is now ingested."""
        assert should_exclude_competition("La Liga") is False

    def test_serie_a_not_excluded(self):
        """Serie A is now ingested."""
        assert should_exclude_competition("Serie A") is False
        assert should_exclude_competition("Italian Serie A") is False

    def test_secondary_leagues_not_excluded(self):
        """Secondary leagues are definitely not excluded."""
        assert should_exclude_competition("German 2 Bundesliga") is False
        assert should_exclude_competition("English Championship") is False
        assert should_exclude_competition("Italian Serie B") is False
        assert should_exclude_competition("Spanish Segunda Division") is False

    def test_unknown_competitions_not_excluded(self):
        """Unknown competitions default to being ingested."""
        assert should_exclude_competition("Fictional League") is False
        assert should_exclude_competition("Random Tournament") is False
        assert should_exclude_competition("XYZ Football") is False


class TestCaseInsensitivity:
    """Test that exclusion patterns are case-insensitive."""

    def test_lowercase_friendly(self):
        """Lowercase 'friendly' should still be excluded."""
        assert should_exclude_competition("international friendly") is True

    def test_uppercase_u21(self):
        """Uppercase 'U21' should still be excluded."""
        assert should_exclude_competition("PREMIER LEAGUE U21") is True

    def test_mixed_case(self):
        """Mixed case should work."""
        assert should_exclude_competition("Women's WORLD Cup") is True


class TestEdgeCases:
    """Test edge cases in exclusion logic."""

    def test_empty_string_not_excluded(self):
        """Empty string should not be excluded (let it fail elsewhere)."""
        assert should_exclude_competition("") is False

    def test_whitespace_only_not_excluded(self):
        """Whitespace should not be excluded."""
        assert should_exclude_competition("   ") is False

    def test_partial_match_in_name(self):
        """Exclusion pattern must match, not just be coincidental."""
        # "Amateur" in "Amateur" matches
        assert should_exclude_competition("Amateur Cup") is True
        # But "ama" doesn't match "Amateur"
        assert should_exclude_competition("Ama League") is False


class TestScoringEnginePhilosophy:
    """
    Tests to document the scoring engine philosophy.

    These aren't testing exclusion logic directly - they document
    how the system should work as a whole.
    """

    def test_philosophy_high_volume_markets_score_low(self):
        """
        Document: High volume markets score low due to volume penalty.

        EPL markets have:
        - Volume: £500k+ → maximum penalty
        - Spread: 1 tick → low score
        - Depth: £50k+ → slight penalty

        Result: They score LOW (~20-35) and won't appear in radar.
        """
        # This is a philosophical test - the actual scoring tests are elsewhere
        pass

    def test_philosophy_secondary_leagues_score_higher(self):
        """
        Document: Secondary leagues score higher.

        2. Bundesliga markets have:
        - Volume: £15k → no penalty
        - Spread: 4-6 ticks → sweet spot
        - Depth: £800 → good range

        Result: They score HIGHER (~50-65) and appear in radar.
        """
        pass

    def test_philosophy_competition_learning(self):
        """
        Document: We learn which competitions are valuable.

        Over time, CompetitionStats tracks:
        - Average score per competition
        - Number of markets above threshold
        - Rolling 30-day average

        Competitions with consistently low scores can be deprioritised.
        """
        pass
