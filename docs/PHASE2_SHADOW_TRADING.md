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

    # Aggregate performance metrics
    "aggregate_shadow_stats": {
        "schedule": "hourly",
        "description": "Calculate running totals, win rates, CLV correlation",
        "enabled_when": "phase2_active",
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
GET  /api/shadow/performance/niche # Performance broken down by niche
GET  /api/shadow/clv-correlation  # CLV vs outcome analysis
POST /api/shadow/toggle           # Enable/disable (admin only)

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

| Metric | Target | Measurement Period |
|--------|--------|-------------------|
| Sample size | 500+ decisions | - |
| Win rate | > 52% | Last 200 decisions |
| Positive CLV | > 55% of trades | Last 200 decisions |
| CLV-Win correlation | > 0.3 | Statistical test |
| Net P&L | Positive | Last 200 decisions |
| Max drawdown | < 20% of peak | Rolling basis |
| Sharpe ratio | > 1.0 | Daily returns |

---

## Implementation Checklist

- [ ] Create `app/tasks/shadow_trading.py` with decision logic
- [ ] Add shadow trading endpoints to API
- [ ] Create Shadow Trading dashboard UI
- [ ] Add phase status indicator to navbar
- [ ] Implement CLV calculation and storage
- [ ] Implement P&L settlement logic
- [ ] Add performance aggregation task
- [ ] Create niche performance breakdown
- [ ] Add safety badges to all UI elements
- [ ] Write tests for decision logic
- [ ] Add configuration validation
- [ ] Create admin toggle for enable/disable

---

## Safety Reminders

1. **Shadow trading = paper trading = NO REAL MONEY**
2. Phase 3 requires explicit code changes - it will NEVER auto-activate
3. All UI must clearly show "PAPER TRADING" status
4. All P&L figures must note they are theoretical
5. Live trading requires separate Betfair API credentials not yet configured
