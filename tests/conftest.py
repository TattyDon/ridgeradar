"""Pytest configuration and fixtures for RidgeRadar tests."""

import pytest


@pytest.fixture
def sample_market_metrics():
    """Sample market metrics for testing."""
    from app.services.scoring.engine import MarketMetrics

    return {
        "high_volume_efficient": MarketMetrics(
            spread_ticks=1,
            volatility=0.015,
            update_rate=4.0,
            depth=12000,
            volume=450000,
            snapshot_count=100,
        ),
        "secondary_league": MarketMetrics(
            spread_ticks=5,
            volatility=0.045,
            update_rate=0.8,
            depth=620,
            volume=18000,
            snapshot_count=50,
        ),
        "illiquid": MarketMetrics(
            spread_ticks=8,
            volatility=0.09,
            update_rate=0.05,
            depth=50,
            volume=1000,
            snapshot_count=10,
        ),
        "optimal": MarketMetrics(
            spread_ticks=5,
            volatility=0.04,
            update_rate=1.0,
            depth=1500,
            volume=20000,
            snapshot_count=50,
        ),
    }


@pytest.fixture
def competition_names():
    """Sample competition names for exclusion testing."""
    return {
        "excluded": [
            "International Friendly",
            "Club Friendly Games",
            "Premier League U21",
            "U19 European Championship",
            "La Liga Reserves",
            "Women's World Cup",
            "Amateur League Division 1",
        ],
        "included": [
            "English Premier League",
            "German 2 Bundesliga",
            "Spanish Segunda Division",
            "Italian Serie B",
            "English Championship",
            "Dutch Eredivisie",
            "French Ligue 2",
            "Turkish Super Lig",
            "Unknown League",
        ],
    }
