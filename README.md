# RidgeRadar

**Betfair Exchange market radar and exploitability scoring platform**

Phase 1: Shadow Mode - Measurement Infrastructure

---

## Overview

RidgeRadar identifies structural inefficiencies in betting markets by analyzing market microstructure. Rather than pre-judging leagues by name, it **ingests all competitions** and lets the **scoring engine filter** based on actual market data.

### Key Principles

1. **Score-Based Filtering**
   - We ingest ALL competitions (EPL, UCL, 2. Bundesliga, everything)
   - The scoring engine automatically penalises efficient markets
   - No need to guess which leagues are "good" - the data tells us

2. **High Volume = PENALTY**
   - Markets with high matched volume are efficient
   - Volume penalty ensures EPL/UCL score LOW automatically
   - Secondary leagues with moderate volume score HIGHER

3. **Competition Learning**
   - Track which competitions consistently produce high-scoring markets
   - Learn from data over time, not static configuration
   - Adapt to changing market conditions

4. **Shadow Mode First**
   - Phase 1 is measurement only
   - No betting, no live execution
   - Prove the system works before risking capital

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Betfair API credentials

### Setup

1. **Clone and configure:**
   ```bash
   cd ridgeradar
   cp .env.example .env
   # Edit .env with your Betfair credentials
   ```

2. **Run bootstrap:**
   ```bash
   chmod +x scripts/bootstrap.sh
   ./scripts/bootstrap.sh
   ```

3. **Access the UI:**
   - Dashboard: http://localhost:8000
   - API Docs: http://localhost:8000/docs

---

## Architecture

```
ridgeradar/
├── app/
│   ├── api/routes/      # FastAPI endpoints
│   ├── ui/templates/    # Jinja2 templates
│   ├── services/
│   │   ├── betfair_client/  # API client with auth & rate limiting
│   │   ├── ingestion/       # Discovery & snapshot capture
│   │   ├── profiling/       # Metric aggregation
│   │   └── scoring/         # Exploitability scoring
│   ├── models/          # SQLAlchemy models
│   ├── tasks/           # Celery tasks
│   ├── migrations/      # Alembic migrations
│   └── config/          # Configuration
├── tests/
├── docker/
└── scripts/
```

### Services

| Service | Description |
|---------|-------------|
| **app** | FastAPI web application |
| **celery** | Background task workers |
| **celery-beat** | Task scheduler |
| **db** | PostgreSQL database |
| **redis** | Celery broker & rate limiting |

### Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `discover_markets` | Every 15 min | Fetch competitions, events, markets |
| `capture_snapshots` | Every 60 sec | Capture ladder data for active markets |
| `compute_profiles` | Every hour | Aggregate snapshots into daily profiles |
| `score_markets` | Every 5 min | Calculate exploitability scores |
| `aggregate_competition_stats` | Every hour | Learn which competitions score well |

---

## How Filtering Works

### The Old Way (Removed)
Previously, we pre-classified competitions by name:
- "Premier League" → excluded
- "2. Bundesliga" → primary
- Unknown leagues → secondary

**Problems:** Brittle, maintenance burden, missed opportunities.

### The New Way (Score-Based)

1. **Ingest everything** (except API quota-wasters like friendlies)
2. **Score based on actual market data:**
   - Spread, volatility, depth, update rate
   - **Volume penalty** for efficient markets
3. **Filter by score threshold**

**Result:** EPL markets score ~25-35 (high volume penalty), 2. Bundesliga markets score ~50-65 (no penalty).

### Hard Exclusions (Minimal)

Only these patterns are excluded to save API quota:
- `Friendly` - Unpredictable scheduling
- `U21`, `U19`, `U17` - Youth competitions
- `Reserves` - Reserve leagues
- `Women` - Different liquidity profile (could enable later)
- `Youth`, `Amateur` - Low liquidity

Everything else gets ingested and scored.

---

## Scoring Engine

Markets are scored 0-100 based on:

| Component | Weight | Description |
|-----------|--------|-------------|
| Spread | 25% | Moderate spread (3-8 ticks) = exploitable |
| Volatility | 25% | Price movement = opportunity |
| Update Rate | 15% | Activity level |
| Depth | 20% | Liquidity at best prices |
| Volume Penalty | 15% | **High volume = efficient = PENALTY** |

### Volume Penalty (Key to Filtering)

```yaml
volume:
  threshold: 30000   # Below £30k = no penalty
  max: 200000        # Above £200k = maximum penalty
  hard_cap: 500000   # Above £500k = instant disqualify
```

This is what makes EPL matches score LOW automatically:
- EPL match: £450k volume → maximum penalty → score ~30
- 2. Bundesliga match: £15k volume → no penalty → score ~55

### Score Thresholds

| Score | Meaning | Example |
|-------|---------|---------|
| **70+** | Excellent opportunity | Rare, high-value markets |
| **55-70** | High value | Good secondary league markets |
| **40-55** | Moderate | Worth monitoring |
| **<40** | Low value | Efficient markets (EPL, UCL) |

---

## Competition Learning

The `CompetitionStats` model tracks performance over time:

```
competition_stats
├── avg_score           # Average score of markets
├── max_score           # Highest score seen
├── markets_above_55    # Count of high-value markets
├── markets_above_70    # Count of excellent markets
└── rolling_30d_avg     # 30-day rolling average
```

### What We Learn

- Which competitions consistently produce high-scoring markets
- How market efficiency varies by competition
- Seasonal patterns in liquidity

### Competition Rankings API

```bash
GET /api/competitions/rankings
```

Returns competitions sorted by average score, showing learned value.

---

## API Endpoints

### Health
- `GET /health` - Basic health check
- `GET /ready` - Full readiness check

### Markets
- `GET /api/markets` - List markets
- `GET /api/markets/{id}` - Market detail with snapshots

### Scores
- `GET /api/scores` - List scores with filtering
- `GET /api/scores/top` - Top N markets by score
- `GET /api/scores/stats` - Aggregate statistics

### Competitions
- `GET /api/competitions` - List all competitions
- `GET /api/competitions/rankings` - Rankings by average score
- `GET /api/competitions/{id}/stats` - Detailed competition stats

---

## Development

### Run Tests

```bash
# Run all tests
docker compose run --rm app pytest

# Run with coverage
docker compose run --rm app pytest --cov=app

# Run specific test
docker compose run --rm app pytest tests/unit/test_scoring.py -v
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f celery
```

### Database Operations

```bash
# Run migrations
docker compose run --rm app alembic upgrade head

# Generate new migration
docker compose run --rm app alembic revision --autogenerate -m "description"
```

---

## Configuration

Configuration is loaded from:
1. Environment variables (`.env`)
2. `app/config/defaults.yaml`

Key settings in `defaults.yaml`:

```yaml
global:
  enabled_sports: [soccer, tennis]

  # Only these are hard-excluded (save API quota)
  hard_exclusions:
    competition_patterns:
      - "Friendly"
      - "U21"
      - "U19"
      - "Reserves"
      - "Women"
      - "Youth"
      - "Amateur"

  snapshot_interval_seconds: 60
  discovery_interval_minutes: 15

scoring:
  # Minimum score to display in UI
  min_display_score: 40

  # Score above this is "interesting"
  interesting_threshold: 55

  weights:
    spread: 0.25
    volatility: 0.25
    update_rate: 0.15
    depth: 0.20
    volume_penalty: 0.15  # THIS IS KEY

  normalisation:
    volume:
      threshold: 30000   # Below = no penalty
      max: 200000        # Above = max penalty
      hard_cap: 500000   # Above = disqualify

competition_tracking:
  min_markets_for_stats: 10
  rolling_window_days: 30
  low_value_threshold: 35
  high_value_threshold: 60
```

---

## Phase 1 Acceptance Criteria

- [x] Docker Compose brings up all services
- [x] Database migrations run successfully
- [x] Health/ready endpoints work
- [x] Betfair client with auth and rate limiting
- [x] Discovery ingests all competitions (minimal hard exclusions)
- [x] Snapshot capture stores ladder data
- [x] Profiling aggregates metrics by time bucket
- [x] Scoring engine with volume penalty
- [x] High-volume markets score LOW automatically
- [x] Secondary league markets score HIGHER
- [x] Competition stats track learned performance
- [x] UI shows dashboard, radar, competition rankings
- [x] Score-based filtering (no name-based tier classification)

---

## License

Proprietary - All Rights Reserved
