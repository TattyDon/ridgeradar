# Phase 2: Shadow Trading System

## Overview

Shadow trading is a **paper trading simulation** that records what trades we WOULD make based on the scoring system, without risking real money. This validates whether high scores correlate with profitable opportunities before committing capital.

---

## System States

The system operates in distinct phases with clear visual indicators:

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: DATA COLLECTION                                       │
│  Status: 🟡 COLLECTING                                          │
│  ─────────────────────────────────────────────────────────────  │
│  • Scoring markets and capturing closing data                   │
│  • Shadow trading: DISABLED (waiting for data thresholds)       │
│  • No decisions being recorded                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: SHADOW TRADING                                        │
│  Status: 🟢 ACTIVE (PAPER)                                      │
│  ─────────────────────────────────────────────────────────────  │
│  • Recording hypothetical trading decisions                     │
│  • Tracking theoretical P&L                                     │
│  • NO REAL MONEY AT RISK                                        │
│  • Badge: "📝 PAPER TRADING"                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: LIVE TRADING (Future)                                 │
│  Status: 🔴 NOT IMPLEMENTED                                     │
│  ─────────────────────────────────────────────────────────────  │
│  • Requires manual code changes to enable                       │
│  • Will never auto-activate                                     │
│  • Badge: "💰 LIVE TRADING"                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Activation Thresholds

Shadow trading auto-activates when ALL conditions are met:

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Closing data records | ≥ 500 | Sufficient sample size |
| Settlement results | ≥ 200 | Need outcome data |
| High-score markets (30+) | ≥ 50 | Enough edge candidates |
| Days collecting | ≥ 7 | Avoid day-of-week bias |

**Safety: Phase 3 (live trading) will NEVER auto-activate. It requires:**
1. Manual code deployment
2. Explicit configuration change
3. API credentials for Betfair betting

---

## Shadow Decision Logic

### Entry Criteria

A shadow decision is recorded when:

```python
ENTRY_CRITERIA = {
    # Score threshold - only trade high-scoring markets
    "min_score": 30,

    # Time window - only trade close to kickoff (more reliable prices)
    "min_minutes_to_start": 5,
    "max_minutes_to_start": 60,

    # Liquidity requirements - must be tradeable
    "min_total_matched": 5000,  # £5k+ already matched
    "max_spread_percent": 5.0,  # Back/lay spread < 5%

    # Market status
    "market_status": "OPEN",
    "in_play": False,
}
```

### Decision Rules by Market Type

```python
MARKET_RULES = {
    "MATCH_ODDS": {
        # Back the selection with best value (highest implied edge)
        "strategy": "back_best_value",
        "description": "Back runner where score indicates mispricing",
        "runner_selection": "highest_score_contribution",
    },

    "OVER_UNDER_25": {
        # System tends to find value in unders (less public action)
        "strategy": "back_under",
        "description": "Back Under 2.5 when score is high",
        "runner_selection": "Under 2.5 Goals",
    },

    "BOTH_TEAMS_TO_SCORE": {
        # Back No when score is high (less efficient market)
        "strategy": "back_no",
        "description": "Back 'No' when score indicates value",
        "runner_selection": "No",
    },

    "CORRECT_SCORE": {
        # Skip - too illiquid for reliable signals
        "strategy": "skip",
        "description": "Not traded - insufficient liquidity",
    },

    # Default for unknown market types
    "DEFAULT": {
        "strategy": "skip",
        "description": "Unknown market type - not traded",
    },
}
```

### Stake Sizing

```python
STAKE_CONFIG = {
    # Theoretical stake for P&L tracking
    "base_stake": 10.00,  # £10 per trade

    # Kelly criterion (future enhancement)
    "use_kelly": False,
    "kelly_fraction": 0.25,  # Quarter Kelly

    # Position limits
    "max_stake_per_market": 50.00,
    "max_exposure_per_event": 100.00,
    "max_daily_exposure": 500.00,
}
```

---

## Data Recording

### Shadow Decision Record

When a decision is made, capture:

```python
@dataclass
class ShadowDecisionRecord:
    # Identity
    market_id: int
    runner_id: int
    decision_type: str  # "BACK" or "LAY"

    # Trigger
    score_id: int
    trigger_score: Decimal
    trigger_reason: str  # e.g., "Score 42.5 exceeded threshold 30"

    # Entry conditions (at decision time)
    decision_at: datetime
    minutes_to_start: int
    entry_back_price: Decimal  # Best back price at decision
    entry_lay_price: Decimal   # Best lay price at decision
    entry_spread: Decimal      # Spread as percentage
    available_to_back: Decimal
    available_to_lay: Decimal

    # Theoretical position
    theoretical_stake: Decimal = 10.00

    # Closing prices (populated later)
    closing_back_price: Optional[Decimal] = None
    closing_lay_price: Optional[Decimal] = None
    clv_percent: Optional[Decimal] = None

    # Outcome (populated after settlement)
    outcome: Optional[str] = None  # "WIN", "LOSE", "VOID", "PENDING"
    settled_at: Optional[datetime] = None

    # P&L (populated after settlement)
    gross_pnl: Optional[Decimal] = None
    commission: Optional[Decimal] = None  # Betfair commission estimate
    spread_cost: Optional[Decimal] = None  # Cost of crossing spread
    net_pnl: Optional[Decimal] = None
```

### CLV Calculation

Closing Line Value measures if we got a better price than the market close:

```python
def calculate_clv(entry_price: Decimal, closing_price: Decimal, bet_type: str) -> Decimal:
    """
    Calculate Closing Line Value.

    For BACK bets: CLV = (entry_price - closing_price) / closing_price
    - Positive CLV = we got better odds than close (good)
    - Negative CLV = we got worse odds than close (bad)

    For LAY bets: CLV = (closing_price - entry_price) / closing_price
    - Positive CLV = we laid at lower odds than close (good)
    """
    if bet_type == "BACK":
        return (entry_price - closing_price) / closing_price * 100
    else:  # LAY
        return (closing_price - entry_price) / closing_price * 100
```

### P&L Calculation

```python
def calculate_pnl(
    stake: Decimal,
    entry_price: Decimal,
    outcome: str,
    bet_type: str,
    commission_rate: Decimal = Decimal("0.05"),  # 5% Betfair commission
) -> dict:
    """Calculate theoretical P&L for a shadow decision."""

    if outcome == "VOID":
        return {"gross_pnl": 0, "commission": 0, "net_pnl": 0}

    if bet_type == "BACK":
        if outcome == "WIN":
            gross_pnl = stake * (entry_price - 1)
            commission = gross_pnl * commission_rate
            net_pnl = gross_pnl - commission
        else:  # LOSE
            gross_pnl = -stake
            commission = Decimal("0")
            net_pnl = gross_pnl

    else:  # LAY
        if outcome == "WIN":  # Selection lost, lay wins
            gross_pnl = stake
            commission = gross_pnl * commission_rate
            net_pnl = gross_pnl - commission
        else:  # LOSE (selection won, lay loses)
            gross_pnl = -stake * (entry_price - 1)
            commission = Decimal("0")
            net_pnl = gross_pnl

    return {
        "gross_pnl": gross_pnl,
        "commission": commission,
        "net_pnl": net_pnl,
    }
```

---

## Task Schedule

```python
SHADOW_TRADING_TASKS = {
    # =========================================================================
    # Score-Based Shadow Trading (Original)
    # =========================================================================

    # Make decisions on high-scoring markets approaching kickoff
    "make_shadow_decisions": {
        "schedule": "every 2 minutes",
        "description": "Check for markets meeting entry criteria, record decisions",
        "enabled_when": "phase2_active",
    },

    # Capture closing prices for CLV calculation
    "capture_closing_prices": {
        "schedule": "every 2 minutes",
        "description": "Update shadow decisions with closing prices",
        "enabled_when": "phase2_active",
    },

    # Settle decisions after market closes
    "settle_shadow_decisions": {
        "schedule": "every 15 minutes",
        "description": "Determine outcomes and calculate P&L",
        "enabled_when": "phase2_active",
    },

    # =========================================================================
    # Hypothesis-Based Evaluation (NEW)
    # =========================================================================

    # Evaluate all active hypotheses against momentum signals
    "evaluate_hypotheses": {
        "schedule": "every 2 minutes",
        "description": "Find momentum signals, match against hypotheses, create decisions",
        "enabled_when": "phase2_active",
    },

    # Update denormalized hypothesis statistics
    "update_hypothesis_stats": {
        "schedule": "hourly at :15",
        "description": "Aggregate win/loss/P&L stats for each hypothesis",
        "enabled_when": "always",
    },
}
```

---

## UI Components

### 1. Shadow Trading Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  📝 SHADOW TRADING                              [PAPER MODE]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Status: 🟢 ACTIVE          Started: 2024-02-05                │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Decisions │  │   Win Rate  │  │   Net P&L   │             │
│  │     127     │  │    58.3%    │  │   +£234.50  │             │
│  │   recorded  │  │  (74 W/53 L)│  │  theoretical│             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
│  CLV Analysis:                                                  │
│  • Avg CLV (all): +1.2%                                        │
│  • Avg CLV (winners): +2.1%                                    │
│  • Avg CLV (losers): +0.1%                                     │
│  • CLV > 0 correlation with wins: 62%                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Recent Decisions Table

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  Recent Shadow Decisions                                    [Paper Trading]   │
├────────────────────────────────────────────────────────────────────────────────┤
│ Time     │ Competition       │ Market      │ Selection │ Entry │ CLV   │ P&L  │
├──────────┼───────────────────┼─────────────┼───────────┼───────┼───────┼──────┤
│ 14:32    │ Serie B           │ Match Odds  │ BACK Home │ 2.40  │ +2.1% │ +£14 │
│ 14:15    │ K League 2        │ O/U 2.5     │ BACK Under│ 1.85  │ -0.5% │ -£10 │
│ 13:58    │ Primeira Liga     │ BTTS        │ BACK No   │ 2.10  │ +1.8% │ +£11 │
│ 13:45    │ Allsvenskan       │ Match Odds  │ BACK Draw │ 3.50  │ +3.2% │ 🕐   │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 3. Performance by Niche

```
┌─────────────────────────────────────────────────────────────────┐
│  Performance by Niche                          [Paper Trading] │
├─────────────────────────────────────────────────────────────────┤
│ Niche                    │ Trades │ Win %  │ Avg CLV │ Net P&L │
├──────────────────────────┼────────┼────────┼─────────┼─────────┤
│ Serie B - Match Odds     │   23   │ 65.2%  │  +2.4%  │  +£87   │
│ K League 2 - O/U 2.5     │   18   │ 55.6%  │  +1.1%  │  +£32   │
│ Allsvenskan - Match Odds │   15   │ 60.0%  │  +1.8%  │  +£45   │
│ Liga MX - BTTS           │   12   │ 50.0%  │  +0.2%  │  -£8    │
└─────────────────────────────────────────────────────────────────┘
```

### 4. Safety Indicators

Every shadow trading UI element MUST include:

```html
<!-- Always visible badge -->
<span class="badge bg-warning text-dark">
    <i class="bi bi-pencil-square me-1"></i>PAPER TRADING
</span>

<!-- Disclaimer on all P&L figures -->
<small class="text-muted">
    * Theoretical results. No real money at risk.
</small>

<!-- Phase indicator -->
<div class="alert alert-info">
    <strong>Phase 2: Shadow Trading</strong><br>
    Recording hypothetical decisions to validate strategy.
    Live trading (Phase 3) is NOT enabled.
</div>
```

---

## API Endpoints

```python
# Shadow Trading Endpoints
GET  /api/shadow/status           # Current phase, activation status
GET  /api/shadow/decisions        # List recent decisions
GET  /api/shadow/decision/{id}    # Single decision details
GET  /api/shadow/performance      # Aggregate performance metrics
GET  /api/shadow/niche-performance # Performance broken down by niche
GET  /api/shadow/clv-correlation  # CLV vs outcome analysis
GET  /api/shadow/daily-pnl        # Daily P&L for charting

# Hypothesis Endpoints (NEW)
GET  /api/hypotheses/                    # List all hypotheses with stats
GET  /api/hypotheses/compare             # Compare performance across hypotheses
GET  /api/hypotheses/{name}              # Get hypothesis details
GET  /api/hypotheses/{name}/decisions    # Get decisions for a hypothesis
GET  /api/hypotheses/{name}/daily-pnl    # Daily P&L for a hypothesis
POST /api/hypotheses/{name}/toggle       # Enable/disable a hypothesis
POST /api/hypotheses/seed                # Seed default hypotheses

# Response always includes safety flag
{
    "mode": "PAPER",
    "real_money_at_risk": false,
    "decisions": [...],
    "disclaimer": "Theoretical results only. No real trades executed."
}
```

---

## Configuration

```yaml
# config/shadow_trading.yaml

shadow_trading:
  # Activation
  enabled: true
  auto_activate_phase2: true

  # Entry criteria
  min_score_threshold: 30
  min_minutes_to_start: 5
  max_minutes_to_start: 60
  min_liquidity: 5000
  max_spread_percent: 5.0

  # Stake sizing
  base_stake: 10.00
  max_stake_per_market: 50.00
  max_daily_exposure: 500.00

  # Commission estimate
  commission_rate: 0.05

  # Safety
  live_trading_enabled: false  # NEVER auto-set to true
  require_manual_activation: true

  # Market type rules
  market_rules:
    MATCH_ODDS:
      enabled: true
      strategy: "back_best_value"
    OVER_UNDER_25:
      enabled: true
      strategy: "back_under"
    BOTH_TEAMS_TO_SCORE:
      enabled: true
      strategy: "back_no"
    CORRECT_SCORE:
      enabled: false
      strategy: "skip"
```

---

## Validation Metrics

Before considering Phase 3, shadow trading should demonstrate:

### Overall System Metrics

| Metric | Target | Measurement Period |
|--------|--------|-------------------|
| Sample size | 500+ decisions | - |
| Win rate | > 52% | Last 200 decisions |
| Positive CLV | > 55% of trades | Last 200 decisions |
| CLV-Win correlation | > 0.3 | Statistical test |
| Net P&L | Positive | Last 200 decisions |
| Max drawdown | < 20% of peak | Rolling basis |
| Sharpe ratio | > 1.0 | Daily returns |

### Per-Hypothesis Metrics (NEW)

| Metric | Target | Notes |
|--------|--------|-------|
| Decisions per hypothesis | 500+ | Statistical significance |
| ROI after costs | > 3% | Per hypothesis |
| Positive CLV rate | > 50% | Indicates edge capture |
| Stability period | 3+ months | Edge must persist |

### Hypothesis Verdicts

Based on performance, each hypothesis receives a verdict:

| Verdict | Criteria |
|---------|----------|
| **PROMISING** | ROI > 3%, positive CLV, 50+ settled decisions |
| **MARGINAL** | ROI > 0% but < 3%, needs more data |
| **UNPROFITABLE** | ROI < 0% after 100+ decisions |
| **INSUFFICIENT_DATA** | < 50 settled decisions |

Only **PROMISING** hypotheses should be considered for Phase 3.

---

## Trading Hypotheses System

### Overview

The system now supports **multiple concurrent trading hypotheses**, each with different entry criteria and selection logic. This allows scientific A/B testing of different trading strategies.

### What is a Hypothesis?

A trading hypothesis defines:
- **Entry criteria** (score threshold, momentum requirements, time windows)
- **Selection logic** (momentum-based, score-based, contrarian)
- **Decision type** (BACK or LAY)

Multiple hypotheses can run simultaneously, each generating independent shadow decisions.

### Default Hypotheses

The system comes with 5 pre-configured hypotheses:

| Name | Strategy | Entry Criteria |
|------|----------|----------------|
| **steam_follower** | Back steamers in thin markets | Score ≥30, steaming >5%, 1-24h to kickoff |
| **strong_steam_follower** | Pure momentum play | No score requirement, steaming >10% |
| **drift_fader** | Lay drifters (contrarian) | Score ≥40, drifting >8% |
| **score_based_classic** | Traditional score-only | Score ≥50, no momentum requirement |
| **under_specialist** | O/U markets with steam | Score ≥25, steaming >4%, O/U markets only |

### Hypothesis Entry Criteria

```python
# Example: steam_follower hypothesis
{
    "min_score": 30,                      # Exploitability score threshold
    "min_price_change_pct": 5.0,          # Minimum price movement %
    "price_change_direction": "steaming", # "steaming", "drifting", or null
    "price_change_window_minutes": 120,   # Lookback window for momentum
    "min_minutes_to_start": 60,           # Earliest entry (1h before)
    "max_minutes_to_start": 1440,         # Latest entry (24h before)
    "min_total_matched": 5000,            # Minimum liquidity
    "max_spread_pct": 5.0,                # Maximum bid-ask spread
    "market_type_filter": ["MATCH_ODDS", "OVER_UNDER_25"]  # Optional
}
```

### How Hypotheses Are Evaluated

Every 2 minutes (when Phase 2 is active):

1. **Signal Detection**: Scan all markets for price momentum signals
2. **Hypothesis Matching**: Check each signal against all active hypotheses
3. **Decision Creation**: Create shadow decisions for matching signals
4. **Deduplication**: Only one decision per market per hypothesis

### API Endpoints

```
# Hypothesis Management
GET  /api/hypotheses/                    # List all with stats
GET  /api/hypotheses/compare             # Compare performance
GET  /api/hypotheses/{name}              # Get details
GET  /api/hypotheses/{name}/decisions    # Get decisions
GET  /api/hypotheses/{name}/daily-pnl    # Daily P&L data
POST /api/hypotheses/{name}/toggle       # Enable/disable
POST /api/hypotheses/seed                # Seed defaults
```

### Example Response

```json
{
  "name": "steam_follower",
  "display_name": "Steam Follower",
  "enabled": true,
  "total_decisions": 47,
  "wins": 28,
  "losses": 19,
  "win_rate": 59.6,
  "total_pnl": 87.50,
  "avg_clv": 1.8,
  "roi_percent": 4.6
}
```

### Creating Custom Hypotheses

Add to `app/tasks/hypothesis.py`:

```python
{
    "name": "my_custom_hypothesis",
    "display_name": "My Custom Strategy",
    "description": "Description of what this tests",
    "enabled": True,
    "entry_criteria": {
        "min_score": 40,
        "min_price_change_pct": 7.0,
        "price_change_direction": "steaming",
        # ... other criteria
    },
    "selection_logic": "momentum",
    "decision_type": "BACK",
}
```

Then run: `curl -X POST http://localhost:8002/api/hypotheses/seed`

---

## Price Momentum (Steamers/Drifters)

### Now Integrated via Hypotheses

Price momentum is now **actively tested** through the hypothesis system rather than being observational-only:

- **steam_follower**: Tests if following early steam in thin markets is profitable
- **strong_steam_follower**: Tests pure momentum without score validation
- **drift_fader**: Tests contrarian fade of market overreactions
- **under_specialist**: Tests momentum specifically in O/U markets

### What We're Testing

1. **Do steamers win more often?** → Compare win rates across hypotheses
2. **Does score + momentum beat score alone?** → steam_follower vs score_based_classic
3. **Is contrarian viable?** → drift_fader results
4. **Are certain market types more predictable?** → under_specialist vs others

### Data Captured Per Decision

```python
# Momentum data stored with each shadow decision
price_change_30m: Decimal  # % change vs 30 mins ago
price_change_1h: Decimal   # % change vs 1 hour ago
price_change_2h: Decimal   # % change vs 2 hours ago
hypothesis_name: str       # Which strategy triggered this
```

### Validation Path

After 500+ decisions per hypothesis:

1. Compare ROI across hypotheses
2. Analyze CLV correlation for each
3. Identify which strategies show consistent edge
4. Retire unprofitable hypotheses
5. Potentially promote winning strategies to Phase 3

---

## Implementation Checklist

### Core Shadow Trading
- [x] Create `app/tasks/shadow_trading.py` with decision logic
- [x] Add shadow trading endpoints to API (`/api/shadow/*`)
- [x] Create Shadow Trading dashboard UI (`/shadow`)
- [x] Add phase status indicator
- [x] Implement CLV calculation and storage
- [x] Implement P&L settlement logic
- [x] Add performance aggregation task
- [x] Create niche performance breakdown
- [x] Add safety badges to all UI elements

### Hypothesis-Based System (NEW)
- [x] Create `TradingHypothesis` model (`app/models/domain.py`)
- [x] Create hypothesis engine (`app/services/hypothesis_engine.py`)
- [x] Create hypothesis tasks (`app/tasks/hypothesis.py`)
- [x] Add hypothesis API endpoints (`/api/hypotheses/*`)
- [x] Seed default hypotheses (steam_follower, drift_fader, etc.)
- [x] Add momentum data to shadow decisions
- [x] Create database migration for hypothesis tables
- [x] Add hypothesis comparison endpoint
- [x] Track price changes (30m, 1h, 2h) per decision

### Remaining
- [ ] Write tests for hypothesis evaluation logic
- [ ] Add hypothesis management to admin UI
- [ ] Create hypothesis performance charts

---

## Safety Reminders

1. **Shadow trading = paper trading = NO REAL MONEY**
2. Phase 3 requires explicit code changes - it will NEVER auto-activate
3. All UI must clearly show "PAPER TRADING" status
4. All P&L figures must note they are theoretical
5. Live trading requires separate Betfair API credentials not yet configured
