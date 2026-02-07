# RidgeRadar Phase 1: Claude Code Implementation Prompt

## Context

You are building **RidgeRadar**, an exchange-only analytics platform for discovering structural inefficiencies on the Betfair Exchange. This is Phase 1 of a multi-phase project.

**Important:** Read the full specification documents before starting:
- `/docs/betfair_exchange_strategy.md` — Strategy and philosophy
- `/docs/ridgeradar_spec_improved.md` — Technical specification (v2.1)

---

## Project Philosophy (Critical — Must Understand)

RidgeRadar is **NOT** a typical betting system. Key principles:

### 1. Score-Based Filtering (NOT Name-Based)

**The old approach (DON'T DO THIS):**
```python
# BAD - Don't pre-classify by name
if "Premier League" in competition_name:
    tier = "excluded"
elif "2. Bundesliga" in competition_name:
    tier = "primary"
```

**The correct approach:**
```python
# GOOD - Ingest everything, let the scoring engine filter
# The volume penalty automatically makes EPL/UCL score LOW
score = scoring_engine.calculate_score(market_metrics)
# EPL match with £450k volume → score ~30 (low)
# 2. Bundesliga with £15k volume → score ~60 (good)
```

### 2. Why Score-Based Works

The **volume penalty** in the scoring formula naturally filters efficient markets:

| Market | Volume | Volume Penalty | Final Score |
|--------|--------|----------------|-------------|
| EPL: Liverpool vs Chelsea | £450,000 | Maximum (100%) | ~25-35 |
| UCL: Final | £800,000 | Maximum (100%) | ~20-30 |
| 2. Bundesliga match | £15,000 | None (0%) | ~55-70 |
| Copa del Rey (lower teams) | £12,000 | None (0%) | ~60-75 |

**We don't need to guess which leagues are good — the data tells us.**

### 3. Competition Learning

Over time, we track which competitions consistently produce high-scoring markets:

```sql
-- competition_stats table (LEARNED, not pre-configured)
competition_stats
├── avg_score           -- Average score of markets
├── max_score           -- Highest score seen
├── markets_above_55    -- Count of "interesting" markets
├── markets_above_70    -- Count of "excellent" markets
└── rolling_30d_avg     -- Trend over time
```

This reveals opportunities we couldn't have predicted.

### 4. Shadow Mode First

- Phase 1 builds measurement infrastructure only
- No betting, no live execution
- We prove the system works before risking capital

---

## Phase 1 Scope

**Duration:** Weeks 1-4 (Month 1)
**Goal:** Build the data ingestion, profiling, and scoring infrastructure

### Week 1-2 Deliverables: Infrastructure

1. **Project Scaffolding**
   ```
   ridgeradar/
   ├── app/
   │   ├── api/
   │   │   ├── __init__.py
   │   │   ├── routes/
   │   │   │   ├── health.py
   │   │   │   ├── markets.py
   │   │   │   ├── scores.py
   │   │   │   ├── competitions.py
   │   │   │   └── config.py
   │   │   └── dependencies.py
   │   ├── ui/
   │   │   ├── templates/
   │   │   └── static/
   │   ├── services/
   │   │   ├── betfair_client/
   │   │   │   ├── __init__.py
   │   │   │   ├── auth.py
   │   │   │   ├── api.py
   │   │   │   └── rate_limiter.py
   │   │   ├── ingestion/
   │   │   │   ├── __init__.py
   │   │   │   ├── discovery.py
   │   │   │   └── snapshots.py
   │   │   ├── profiling/
   │   │   │   ├── __init__.py
   │   │   │   └── metrics.py
   │   │   └── scoring/
   │   │       ├── __init__.py
   │   │       └── engine.py
   │   ├── models/
   │   │   ├── __init__.py
   │   │   ├── base.py
   │   │   └── domain.py
   │   ├── tasks/
   │   │   ├── __init__.py
   │   │   ├── discovery.py
   │   │   ├── snapshots.py
   │   │   ├── profiling.py
   │   │   ├── scoring.py
   │   │   └── competition_stats.py
   │   ├── migrations/
   │   └── config/
   │       ├── __init__.py
   │       ├── settings.py
   │       └── defaults.yaml
   ├── docker/
   │   ├── Dockerfile
   │   └── docker-compose.yml
   ├── tests/
   │   ├── unit/
   │   ├── integration/
   │   └── fixtures/
   ├── scripts/
   │   └── bootstrap.sh
   ├── pyproject.toml
   ├── .env.example
   └── README.md
   ```

2. **Docker Compose Setup**
   - FastAPI application (port 8000)
   - PostgreSQL 15+ (port 5432)
   - Redis (port 6379)
   - Celery worker(s)
   - Celery beat (scheduler)

3. **Database Schema**

   Create these tables with Alembic migrations:

   ```sql
   -- Sports (permanent)
   CREATE TABLE sports (
       id SERIAL PRIMARY KEY,
       betfair_id VARCHAR(20) UNIQUE NOT NULL,
       name VARCHAR(100) NOT NULL,
       enabled BOOLEAN DEFAULT true,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Competitions - NO tier classification by name
   -- The tier field is only for hard exclusions (Friendly, U21, etc.)
   CREATE TABLE competitions (
       id SERIAL PRIMARY KEY,
       betfair_id VARCHAR(50) UNIQUE NOT NULL,
       sport_id INTEGER REFERENCES sports(id),
       name VARCHAR(200) NOT NULL,
       country_code VARCHAR(10),
       enabled BOOLEAN DEFAULT true,
       priority INTEGER DEFAULT 0,
       tier VARCHAR(20) DEFAULT 'active',  -- 'active' or 'excluded' (hard exclusions only)
       created_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Competition statistics (LEARNED from data)
   -- This is the key to score-based filtering
   CREATE TABLE competition_stats (
       id SERIAL PRIMARY KEY,
       competition_id INTEGER REFERENCES competitions(id),
       stats_date DATE NOT NULL,
       markets_scored INTEGER DEFAULT 0,
       avg_score DECIMAL(6,2),
       max_score DECIMAL(6,2),
       min_score DECIMAL(6,2),
       score_std_dev DECIMAL(6,2),
       avg_volume DECIMAL(15,2),
       total_volume DECIMAL(15,2),
       avg_spread_ticks DECIMAL(8,4),
       markets_above_40 INTEGER DEFAULT 0,
       markets_above_55 INTEGER DEFAULT 0,
       markets_above_70 INTEGER DEFAULT 0,
       rolling_30d_avg_score DECIMAL(6,2),
       created_at TIMESTAMPTZ DEFAULT NOW(),
       updated_at TIMESTAMPTZ DEFAULT NOW(),
       UNIQUE(competition_id, stats_date)
   );

   -- Events
   CREATE TABLE events (
       id SERIAL PRIMARY KEY,
       betfair_id VARCHAR(50) UNIQUE NOT NULL,
       competition_id INTEGER REFERENCES competitions(id),
       name VARCHAR(300) NOT NULL,
       scheduled_start TIMESTAMPTZ NOT NULL,
       status VARCHAR(20) DEFAULT 'SCHEDULED',
       created_at TIMESTAMPTZ DEFAULT NOW(),
       updated_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Markets
   CREATE TABLE markets (
       id SERIAL PRIMARY KEY,
       betfair_id VARCHAR(50) UNIQUE NOT NULL,
       event_id INTEGER REFERENCES events(id),
       name VARCHAR(200) NOT NULL,
       market_type VARCHAR(50) NOT NULL,
       total_matched DECIMAL(15,2) DEFAULT 0,
       status VARCHAR(20) DEFAULT 'OPEN',
       in_play BOOLEAN DEFAULT false,
       created_at TIMESTAMPTZ DEFAULT NOW(),
       updated_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Runners
   CREATE TABLE runners (
       id SERIAL PRIMARY KEY,
       betfair_id BIGINT NOT NULL,
       market_id INTEGER REFERENCES markets(id),
       name VARCHAR(200) NOT NULL,
       sort_priority INTEGER,
       status VARCHAR(20) DEFAULT 'ACTIVE',
       UNIQUE(betfair_id, market_id)
   );

   -- Market snapshots (partitioned by date)
   CREATE TABLE market_snapshots (
       id BIGSERIAL,
       market_id INTEGER NOT NULL REFERENCES markets(id),
       captured_at TIMESTAMPTZ NOT NULL,
       total_matched DECIMAL(15,2),
       total_available DECIMAL(15,2),
       overround DECIMAL(6,4),
       ladder_data JSONB NOT NULL,
       PRIMARY KEY (id, captured_at)
   ) PARTITION BY RANGE (captured_at);

   -- Daily profiles
   CREATE TABLE market_profiles_daily (
       id SERIAL PRIMARY KEY,
       market_id INTEGER REFERENCES markets(id),
       profile_date DATE NOT NULL,
       time_bucket VARCHAR(20) NOT NULL,
       avg_spread_ticks DECIMAL(8,4),
       spread_volatility DECIMAL(8,4),
       avg_depth_best DECIMAL(15,2),
       depth_5_ticks DECIMAL(15,2),
       total_matched_volume DECIMAL(15,2),
       update_rate_per_min DECIMAL(8,4),
       price_volatility DECIMAL(8,6),
       mean_price DECIMAL(10,4),
       snapshot_count INTEGER,
       UNIQUE(market_id, profile_date, time_bucket)
   );

   -- Exploitability scores
   CREATE TABLE exploitability_scores (
       id SERIAL PRIMARY KEY,
       market_id INTEGER REFERENCES markets(id),
       runner_id INTEGER REFERENCES runners(id),
       scored_at TIMESTAMPTZ NOT NULL,
       time_bucket VARCHAR(20) NOT NULL,
       odds_band VARCHAR(20) NOT NULL,
       spread_score DECIMAL(6,2),
       volatility_score DECIMAL(6,2),
       update_score DECIMAL(6,2),
       depth_score DECIMAL(6,2),
       volume_penalty DECIMAL(6,2),
       total_score DECIMAL(6,2) NOT NULL,
       config_version_id INTEGER,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );

   -- Configuration versions
   CREATE TABLE config_versions (
       id SERIAL PRIMARY KEY,
       config_type VARCHAR(50) NOT NULL,
       config_data JSONB NOT NULL,
       created_by VARCHAR(100),
       created_at TIMESTAMPTZ DEFAULT NOW(),
       is_active BOOLEAN DEFAULT false
   );

   -- Job audit log
   CREATE TABLE job_runs (
       id SERIAL PRIMARY KEY,
       job_name VARCHAR(100) NOT NULL,
       started_at TIMESTAMPTZ NOT NULL,
       completed_at TIMESTAMPTZ,
       status VARCHAR(20) NOT NULL,
       records_processed INTEGER DEFAULT 0,
       error_message TEXT,
       metadata JSONB
   );

   -- Indexes
   CREATE INDEX idx_events_scheduled ON events(scheduled_start) WHERE status = 'SCHEDULED';
   CREATE INDEX idx_markets_status ON markets(status, event_id);
   CREATE INDEX idx_snapshots_market_time ON market_snapshots(market_id, captured_at DESC);
   CREATE INDEX idx_scores_total ON exploitability_scores(total_score DESC) WHERE total_score > 50;
   CREATE INDEX idx_competition_stats_date ON competition_stats(competition_id, stats_date);
   ```

4. **Configuration System**

   Create `app/config/defaults.yaml`:

   ```yaml
   # RidgeRadar Configuration v2.1
   #
   # PHILOSOPHY: Score-based filtering, not name-based
   # - Ingest ALL competitions for enabled sports
   # - Let the scoring engine's volume penalty filter efficient markets
   # - Learn which competitions are valuable over time

   global:
     enabled_sports:
       - soccer
       - tennis

     # Hard exclusions ONLY - these waste API quota
     # Everything else gets ingested and scored
     hard_exclusions:
       sports:
         - basketball
         - american_football
         - golf
         - cricket
         - rugby
         - baseball
         - ice_hockey
         - darts
         - snooker
         - boxing
         - mma
       competition_patterns:
         - "Friendly"
         - "U21"
         - "U19"
         - "U17"
         - "Reserves"
         - "Women"  # Different liquidity profile
         - "Youth"
         - "Amateur"

     enabled_market_types:
       - MATCH_ODDS
       - OVER_UNDER_25
       - BOTH_TEAMS_TO_SCORE

     snapshot_interval_seconds: 60
     ladder_depth: 3
     max_markets_per_snapshot: 40
     discovery_interval_minutes: 15
     lookahead_hours: 72
     ignore_inplay: true

     max_markets_active: 500
     max_events_per_competition: 50

   scoring:
     version: "2.0.0"
     min_display_score: 40
     interesting_threshold: 55

     # Weights sum to ~1.0
     weights:
       spread: 0.25
       volatility: 0.25
       update_rate: 0.15
       depth: 0.20
       volume_penalty: 0.15  # KEY: High volume = penalty

     normalisation:
       spread:
         min_ticks: 2
         sweet_spot_max: 8
         max_ticks: 12
       volatility:
         target: 0.04
         max: 0.12
       update_rate:
         min: 0.2
         max: 3.0
       depth:
         min: 150
         optimal: 1500
         max: 8000
       volume:
         # CRITICAL: This filters efficient markets automatically
         threshold: 30000   # Below £30k = no penalty
         max: 200000        # Above £200k = maximum penalty
         hard_cap: 500000   # Above £500k = score 0

     guards:
       absolute_min_depth: 100
       absolute_max_spread_ticks: 20
       min_snapshots_required: 5
       min_update_rate: 0.1

   # Competition learning settings
   competition_tracking:
     min_markets_for_stats: 10
     rolling_window_days: 30
     low_value_threshold: 35
     high_value_threshold: 60

   celery:
     task_schedules:
       discover_markets:
         schedule: 900
         timeout: 300
       capture_snapshots:
         schedule: 60
         timeout: 45
       compute_daily_profiles:
         schedule: 3600
         timeout: 600
       score_markets:
         schedule: 300
         timeout: 180
       aggregate_competition_stats:
         schedule: 3600
         timeout: 300
   ```

### Week 3-4 Deliverables: Ingestion & Scoring

5. **Market Discovery Task**

   ```python
   # app/tasks/discovery.py

   @celery.task(bind=True, max_retries=3)
   def discover_markets(self):
       """
       Scheduled: Every 15 minutes
       Timeout: 5 minutes

       Process:
       1. Fetch enabled sports from config
       2. Fetch ALL competitions (only hard exclusions applied)
       3. For each competition:
          a. Check against hard_exclusions.competition_patterns
          b. If matches pattern → set tier='excluded', skip events
          c. Otherwise → set tier='active', fetch events
       4. Fetch events (next 72 hours)
       5. Fetch market catalogues
       6. Upsert all entities to database
       7. Mark stale events as CLOSED

       CRITICAL: No tier classification based on league names!
       We ingest EPL, UCL, everything - the scoring engine filters.
       """
       pass
   ```

6. **Scoring Engine**

   ```python
   # app/services/scoring/engine.py

   class ScoringEngine:
       """
       Calculate exploitability scores.

       Formula:
       score = 100 × (
           w_spread × f_spread(spread)
         + w_volatility × f_volatility(volatility)
         + w_update × f_update(update_rate)
         + w_depth × f_depth(depth)
         - w_volume × f_volume(volume)  # PENALTY!
       )

       The volume penalty is what makes this work:
       - EPL match (£450k volume) → f_volume returns ~1.0 → big penalty
       - 2. Bundesliga (£15k volume) → f_volume returns 0 → no penalty
       """

       def f_volume(self, volume: float) -> float:
           """
           PENALTY function for matched volume.

           This is the key to score-based filtering.
           High volume = efficient market = bad for us = PENALTY.
           """
           threshold = self.config.volume.threshold  # £30,000
           max_vol = self.config.volume.max  # £200,000
           hard_cap = self.config.volume.hard_cap  # £500,000

           if volume <= threshold:
               return 0  # No penalty
           if volume >= hard_cap:
               return 1.0  # Maximum penalty

           # Linear scale between threshold and max
           return (volume - threshold) / (max_vol - threshold)
   ```

7. **Competition Stats Aggregation Task**

   ```python
   # app/tasks/competition_stats.py

   @celery.task(bind=True)
   def aggregate_competition_stats(self, target_date: date = None):
       """
       Scheduled: Hourly
       Timeout: 5 minutes

       This is the LEARNING component of score-based filtering.

       For each competition with scores today:
       1. Calculate avg_score, max_score, min_score, std_dev
       2. Count markets above thresholds (40, 55, 70)
       3. Calculate rolling 30-day average
       4. Store in competition_stats table

       Over time, this reveals which competitions are valuable
       WITHOUT us having to guess based on names.
       """
       pass
   ```

8. **Competition Rankings API**

   ```python
   # app/api/routes/competitions.py

   @router.get("/rankings")
   async def competition_rankings(db: AsyncSession = Depends(get_db)):
       """
       Returns competitions ranked by learned value.

       This is the output of score-based filtering:
       - We ingested everything
       - The scoring engine rated each market
       - This aggregates to show which competitions are best
       """
       query = (
           select(Competition, CompetitionStats)
           .join(CompetitionStats)
           .where(
               Competition.enabled == True,
               CompetitionStats.stats_date == today(),
               CompetitionStats.markets_scored >= 10,
           )
           .order_by(CompetitionStats.avg_score.desc())
       )
       # Return ranked competitions with their learned stats
   ```

9. **Basic UI**

   **Dashboard (`/`):**
   - System health indicators
   - Top 10 markets by score
   - Score distribution (High/Medium/Low counts)
   - "How It Works" section explaining score-based filtering

   **Market Radar (`/radar`):**
   - Sortable table with filters (Min Score, Time Bucket, Odds Band)
   - Deduplicated - only latest score per market
   - Columns: Competition, Event, Market, Bucket, Spread, Vol, Depth, Score

   **Competitions (`/competitions`):**
   - Ranked by average score (LEARNED, not pre-configured)
   - Shows: avg_score, max_score, markets_above_55, markets_above_70
   - This is the evidence that score-based filtering works

---

## Technical Requirements

### Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Runtime | Python | 3.11+ |
| Web Framework | FastAPI | 0.100+ |
| Task Queue | Celery | 5.3+ |
| Broker | Redis | 7+ |
| Database | PostgreSQL | 15+ |
| ORM | SQLAlchemy | 2.0+ |
| Migrations | Alembic | 1.12+ |
| Templates | Jinja2 | 3.1+ |
| CSS | Bootstrap | 5.3 |
| Interactivity | HTMX | 1.9+ |

### Code Quality

- Type hints on all functions
- Docstrings explaining the score-based philosophy
- Black formatting, Ruff linting
- pytest with 80% coverage on scoring engine

---

## Acceptance Criteria

Phase 1 is complete when:

### Infrastructure
- [ ] Docker Compose brings up all services
- [ ] Database migrations run successfully
- [ ] Health endpoints work

### Data Ingestion
- [ ] Discovery ingests ALL competitions (not filtered by name)
- [ ] Only hard exclusions (Friendly, U21, etc.) are skipped
- [ ] EPL, UCL, etc. ARE ingested (the scoring engine will filter)
- [ ] Snapshots capture every 60 seconds
- [ ] 10,000+ snapshots in first 48 hours

### Scoring Engine
- [ ] Volume penalty works correctly:
  - Market with £450k volume → score < 40
  - Market with £15k volume → score > 50 (all else equal)
- [ ] High-volume markets automatically deprioritised
- [ ] Scores range 0-100 with good distribution

### Competition Learning
- [ ] `competition_stats` table populated
- [ ] Rankings show which competitions score best
- [ ] We can identify valuable competitions WITHOUT name matching

### UI
- [ ] Dashboard shows score distribution
- [ ] Radar shows deduplicated markets
- [ ] Competitions page shows learned rankings
- [ ] "How It Works" explains the philosophy

---

## Example Test Cases

```python
# tests/unit/test_scoring.py

def test_high_volume_gets_penalised():
    """EPL-like market should score low due to volume penalty."""
    engine = ScoringEngine()

    # EPL match characteristics
    result = engine.calculate_score(MarketMetrics(
        spread_ticks=1,      # Very tight (efficient)
        volatility=0.015,    # Very stable (efficient)
        update_rate=4.0,     # Very active
        depth=12000,         # Very deep (efficient)
        volume=450000,       # HIGH VOLUME = PENALTY
    ))

    assert result.total_score < 40  # Should score LOW
    assert result.volume_penalty > 80  # High penalty applied

def test_moderate_volume_no_penalty():
    """2. Bundesliga-like market should score well."""
    engine = ScoringEngine()

    result = engine.calculate_score(MarketMetrics(
        spread_ticks=5,      # Moderate spread
        volatility=0.045,    # Good volatility
        update_rate=0.8,     # Moderate activity
        depth=620,           # Adequate depth
        volume=18000,        # LOW VOLUME = NO PENALTY
    ))

    assert result.total_score > 55  # Should score WELL
    assert result.volume_penalty == 0  # No penalty

def test_volume_penalty_function():
    """Volume penalty should scale correctly."""
    engine = ScoringEngine()

    # Below threshold = no penalty
    assert engine.f_volume(20000) == 0

    # At threshold = no penalty
    assert engine.f_volume(30000) == 0

    # Above threshold = penalty starts
    assert 0 < engine.f_volume(100000) < 1

    # At max = high penalty
    assert engine.f_volume(200000) >= 0.9

    # Above hard cap = maximum penalty
    assert engine.f_volume(500000) == 1.0


# tests/integration/test_competition_learning.py

async def test_competition_stats_populated():
    """After scoring, competition_stats should be populated."""
    # Run discovery, snapshots, scoring tasks
    await discover_markets()
    await capture_snapshots()
    await score_markets()
    await aggregate_competition_stats()

    # Check stats exist
    stats = await db.execute(
        select(CompetitionStats)
        .where(CompetitionStats.stats_date == today())
    )
    assert len(stats.all()) > 0

async def test_rankings_reflect_scores():
    """Competition rankings should match actual scoring data."""
    rankings = await get_competition_rankings()

    # Highest ranked should have highest avg_score
    for i in range(len(rankings) - 1):
        assert rankings[i].avg_score >= rankings[i+1].avg_score
```

---

## Important Reminders

1. **DO ingest EPL, UCL, and all major leagues**
   - The scoring engine will make them score LOW automatically
   - No need for name-based exclusions

2. **DON'T pre-classify competitions by name**
   - No "primary", "secondary", "excluded" based on league names
   - Only hard exclusions for API quota (Friendly, U21, etc.)

3. **Volume penalty is the key**
   - This is what makes score-based filtering work
   - High volume = efficient market = penalty = low score

4. **Competition learning reveals value**
   - Over time, `competition_stats` shows which leagues are actually good
   - We might discover opportunities we never expected

5. **The data decides, not assumptions**
   - Copa del Rey might score higher than Serie B
   - Albanian Superliga might beat Eredivisie
   - Trust the scores, not your intuition

---

## Summary

The key insight of RidgeRadar v2.1 is:

> **We don't need to guess which leagues are efficient. The volume penalty tells us.**

Every Premier League match has £300-500k matched volume. The volume penalty makes these score 25-35 automatically. We don't need to exclude them by name.

Every 2. Bundesliga match has £10-20k matched volume. No volume penalty. They score 50-70 if the structure is good.

**Ingest everything. Score everything. Let the data decide.**
