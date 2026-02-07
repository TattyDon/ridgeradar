# Betfair Exchange Strategy & Research Approach

## JL — Exchange-Only Market Inefficiency Framework

---

## Document Information

| Field | Value |
|-------|-------|
| Version | 3.1 |
| Last Updated | 2026-02-07 |
| Status | Active |
| Implementation | [RidgeRadar Specification](./ridgeradar_spec.md) |

### Change Log

| Version | Date | Changes |
|---------|------|---------|
| 3.1 | 2026-02-07 | Updated commission assumption from 4% to 2% (discounted rate). Recalculated cost model and breakeven examples. |
| 3.0 | 2026-02-07 | Replaced hardcoded competition lists with data-driven scoring approach. Added Hypothesis Testing Framework section. Updated Phase 2 with implementation details. |
| 2.0 | 2026-02-04 | Initial structured version |

---

## 1. Purpose

This document defines the long-term strategy and operating approach for developing a sustainable, exchange-only betting system on Betfair.

**The objective is not short-term profit**, but the systematic discovery and exploitation of structural market inefficiencies that survive after costs.

### 1.1 What This Strategy Is

- A disciplined, research-driven approach to finding sustainable edge
- An engineering and data science exercise with betting as the domain
- A capital-preservation-first framework
- A multi-year programme with defined exit criteria

### 1.2 What This Strategy Is Not

- A get-rich-quick scheme
- A form-based tipster service
- A high-frequency trading operation
- A bookmaker arbitrage system

### 1.3 Related Documents

| Document | Purpose |
|----------|---------|
| [RidgeRadar Spec](./ridgeradar_spec.md) | Technical implementation of the market radar and scoring system |
| [Phase 2 Shadow Trading](./PHASE2_SHADOW_TRADING.md) | Shadow trading system documentation |
| Research Log (TBD) | Experiment documentation and findings |
| Operations Runbook (TBD) | Day-to-day operational procedures |

---

## 2. Core Philosophy

### 2.1 Exchange-First Principle

All signals originate from Betfair market structure. External bookmakers are not used for price discovery. The exchange itself is treated as the primary data source.

**Rationale:**
- Bookmaker prices reflect their risk management, not true probability
- Soft bookmaker arbitrage is a dying edge (accounts get restricted)
- Exchange data is transparent and self-consistent
- Our edge comes from *how* the exchange behaves, not *what* bookies think

### 2.2 Structural Over Informational Edge

The system does **not** attempt to beat the market on:

- Team news
- Injuries
- Lineups
- Public sentiment
- Form narratives
- Weather conditions
- Managerial changes

**These are assumed to be efficiently priced within minutes of becoming public.**

Instead, the focus is on structural inefficiencies:

| Inefficiency Type | Description | Why It Persists |
|-------------------|-------------|-----------------|
| Liquidity imbalances | One side of the book is thin | Low attention, professionals absent |
| Spread inefficiencies | Wide bid-ask gaps | Insufficient market makers |
| Timing effects | Price patterns before kickoff | Predictable recreational flow |
| Shallow market regimes | Total liquidity below threshold | Not worth automating for large players |
| Attention gaps | Markets ignored by mainstream | No media coverage, no API bots |

### 2.3 Research-First Discipline

No strategy is promoted to live trading without:

1. **Shadow testing** — Minimum 500 hypothetical decisions logged
2. **Out-of-sample validation** — Performance on unseen time periods
3. **Regime stability analysis** — Edge must persist across 3+ months
4. **Cost-adjusted evaluation** — Profitable *after* commission and slippage

**Speculation without evidence is rejected.** Gut feelings are hypotheses to be tested, not strategies to be deployed.

### 2.4 The Patience Principle

```
Prefer no bet to a marginal bet.
Prefer waiting to forcing.
Prefer skipping a market to trading it poorly.
```

Most days should result in zero activity. High-frequency betting is a sign of undisciplined execution, not opportunity abundance.

---

## 3. Strategic Hypothesis

### 3.1 Where Edge Exists

Sustainable edge on Betfair exists primarily in markets with these characteristics:

| Characteristic | Why It Creates Edge |
|----------------|---------------------|
| Lower automation density | Professional capital absent, slower price discovery |
| Limited media coverage | Fewer eyes, less efficient information processing |
| Less prominent market types | Over/Under, Correct Score ignored vs Match Odds |
| Low-attention time windows | Early week, morning kickoffs, timezone mismatches |
| Moderate liquidity (£5k-£50k) | Too small for institutions, enough to trade |

### 3.2 Market Selection: Data-Driven Approach

**Important:** Rather than maintaining hardcoded lists of "target" or "avoided" competitions, the system uses the **Exploitability Score** to identify opportunities data-driven.

The exploitability score captures:
- Spread width (wider = more exploitable)
- Liquidity depth (thinner = more exploitable)
- Book imbalance (asymmetric = more exploitable)
- Volume patterns (unusual = potentially exploitable)

**This approach is superior to hardcoded lists because:**

1. **Competitions change** — A "secondary" league may become efficient over time as automation increases
2. **Within-competition variance** — Even in efficient leagues, individual matches may have exploitable characteristics
3. **Data validates hypotheses** — If secondary leagues really are more exploitable, the scoring system will surface them naturally
4. **No maintenance burden** — No need to manually curate competition lists

**Validation:** The Niche Performance dashboard tracks which competitions produce the best results. If the hypothesis "secondary leagues are more exploitable" is correct, we should see them dominating high-score decisions.

### 3.3 Regime Hypothesis

Markets cycle through regimes based on:

1. **Time to kickoff** — Efficiency increases as kickoff approaches
2. **Day of week** — Weekend matches more efficient than Tuesday fixtures
3. **Season phase** — Early season less efficient than run-in
4. **Media attention** — TV matches more efficient than non-broadcast

**Hypothesis to test:** The optimal window is 6-24 hours before kickoff, when recreational money has arrived but professional arbitrage is minimal.

---

## 4. Hypothesis Testing Framework

### 4.1 Purpose

Phase 2 shadow trading uses a **hypothesis testing framework** to systematically evaluate different trading strategies. Each hypothesis represents a specific theory about where edge exists.

### 4.2 Default Hypotheses

The system tests these core hypotheses simultaneously:

| Hypothesis | Theory Being Tested | Key Criteria |
|------------|---------------------|--------------|
| **Steam Follower** | Sharp money moves first; following steam captures value | Score ≥30, steam >5%, 6-24h window |
| **Strong Steam (Pure)** | Momentum alone is sufficient signal | No score req, steam >10% |
| **Drift Fader** | Drift in thin markets = overreaction to fade | LAY drifters, score ≥40, drift >8% |
| **Score-Based (Baseline)** | Exploitability score alone predicts outcomes | Score ≥50, no momentum |
| **Over/Under Specialist** | O/U markets less efficient than Match Odds | O/U only, steam >4% |
| **Correct Score Value** | Correct Score markets are ignored and exploitable | CORRECT_SCORE only, score ≥35 |
| **Shallow Market Edge** | £1k-£5k markets ignored by institutions | £1k-£5k liquidity, score ≥45 |

### 4.3 Hypothesis Comparison Metrics

Each hypothesis is evaluated on:

| Metric | Target | Notes |
|--------|--------|-------|
| Win Rate | 48-55% | At typical odds |
| ROI (after costs) | >3% | Must survive commission |
| CLV (Closing Line Value) | >0% | Were we getting good prices? |
| Sample Size | 500+ decisions | Statistical significance |
| Regime Stability | 3+ months | Edge must persist |

### 4.4 Creating Custom Hypotheses

The Strategy Builder UI allows creating custom hypotheses to test specific theories:

```
Example: "Does steam work better in Portuguese Liga?"

Create hypothesis with:
- name: portuguese_steam_test
- min_score: 25
- price_change_direction: steaming
- min_price_change_pct: 5
- competition_filter: [Portuguese Primeira Liga ID]
```

### 4.5 Hypothesis Lifecycle

```
1. CREATE    → Define entry criteria, enable hypothesis
2. COLLECT   → System logs shadow decisions automatically
3. EVALUATE  → Review performance after 500+ decisions
4. DECIDE    → ADOPT (promote to live) / REJECT / MODIFY
```

---

## 5. Development Phases

### Phase 1 — Infrastructure & Measurement

**Duration:** 3-6 months
**Capital at Risk:** £0
**Focus:** Build, measure, learn

#### Objectives

- [x] Build ingestion pipeline (RidgeRadar)
- [x] Capture market microstructure data across target universe
- [x] Profile liquidity and volatility by competition
- [x] Rank markets by exploitability score
- [x] Establish clean data history (minimum 10,000 snapshots)

#### Phase 1 Exit Criteria

| Criterion | Target | Status |
|-----------|--------|--------|
| Markets tracked | 500+ unique markets | ✓ |
| Competitions covered | 15+ target leagues | ✓ |
| Snapshot volume | 10,000+ snapshots | ✓ |
| Data quality | <1% missing/corrupt | ✓ |
| System uptime | >95% | ✓ |
| Exploitability scores | Calibrated and stable | ✓ |

#### Phase 1 Deliverables

1. Working RidgeRadar deployment ✓
2. Initial exploitability rankings by competition ✓
3. Regime profile report (liquidity patterns by time/odds) ✓
4. List of 5-10 candidate niches for Phase 2 ✓

**No live betting in Phase 1.** ✓

---

### Phase 2 — Shadow Trading & Validation (CURRENT)

**Duration:** 6-12 months
**Capital at Risk:** £0 (shadow only)
**Focus:** Validate hypotheses, find stable niches

#### Implementation

Phase 2 is implemented via:

1. **Hypothesis Engine** — Evaluates markets against hypothesis criteria every 2 minutes
2. **Shadow Decisions** — Records theoretical trades with entry prices
3. **Settlement Tracking** — Tracks outcomes and calculates theoretical P&L
4. **Performance Dashboard** — Compares hypothesis performance

#### Active Hypotheses

See Section 4.2 for the 7 default hypotheses being tested.

#### Shadow Trading Protocol

```
Every 2 minutes when Phase 2 is active:
  1. Scan all markets 6-24h from kickoff
  2. For each enabled hypothesis:
     a. Check if any market/runner meets entry criteria
     b. If match found, create shadow decision
     c. Record: entry price, score, momentum data, timestamp
  3. Settlement task runs hourly:
     a. Check for settled markets
     b. Calculate theoretical P&L with commission
     c. Update hypothesis statistics
```

#### Phase 2 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Shadow decisions logged | 2,000+ total |
| Hypotheses evaluated | 7+ |
| Stable hypotheses identified | 2+ with positive ROI |
| Shadow ROI (best hypothesis) | >3% after costs |
| Regime persistence | Edge stable over 3+ months |
| False positive rate | <20% of "high score" markets unprofitable |

#### Phase 2 Go/No-Go Decision

At end of Phase 2:

```
IF stable_hypotheses >= 2 AND shadow_roi > 3% AND regime_stable:
    PROCEED to Phase 3
ELSE IF partial_signal AND more_data_needed:
    EXTEND Phase 2 by 3 months (once only)
ELSE:
    STOP programme, document learnings
```

**Minimal live exposure in Phase 2** — may place occasional small bets to validate execution assumptions.

---

### Phase 3 — Controlled Deployment

**Duration:** 12-24 months
**Capital at Risk:** £1,000-£5,000 bankroll
**Focus:** Validate in live conditions, refine execution

#### Objectives

- [ ] Activate small-stake trading in proven hypotheses only
- [ ] Enforce strict risk limits (max 2% bankroll per bet)
- [ ] Monitor for drift between shadow and live performance
- [ ] Validate execution quality (slippage, fill rates)
- [ ] Expand selectively to adjacent hypotheses

#### Staking Rules (Phase 3)

| Parameter | Value |
|-----------|-------|
| Starting bankroll | £1,000-£5,000 |
| Max stake per bet | 2% of bankroll |
| Max daily exposure | 10% of bankroll |
| Max weekly exposure | 25% of bankroll |
| Stop-loss trigger | 20% drawdown from peak |

#### Phase 3 Exit Criteria

| Criterion | Target |
|-----------|--------|
| Live bets placed | 500+ |
| Live ROI | >2% after costs |
| Drawdown | <15% peak-to-trough |
| Shadow-to-live correlation | >0.7 |
| Execution quality | Slippage <0.5% on average |

**No aggressive scaling in Phase 3.**

---

### Phase 4 — Selective Scaling

**Duration:** 24+ months
**Capital at Risk:** £5,000-£20,000 bankroll
**Focus:** Maximise proven edge, retire degraded hypotheses

#### Objectives

- [ ] Increase stakes only in hypotheses with 12+ months live track record
- [ ] Retire degraded hypotheses promptly (no emotional attachment)
- [ ] Rebalance focus dynamically based on regime health
- [ ] Preserve capital above all else
- [ ] Consider ML enhancement for stable hypotheses only

#### Scaling Rules

```
Hypothesis qualifies for scaling IF:
  - 12+ months live trading
  - 500+ live bets
  - ROI > 3% after costs
  - Drawdown < 15%
  - Regime shows no degradation trend

Scale increment: 50% stake increase, reassess after 3 months
```

**Scaling follows evidence, not confidence.**

---

## 6. Cost Model

### 6.1 Betfair Commission Structure

| Discount Level | Commission Rate | Typical Profile |
|----------------|-----------------|-----------------|
| Standard | 5.0% | New accounts |
| Discount 1 | 4.0% | £1,000+ monthly volume |
| Discount 2 | 3.0% | £5,000+ monthly volume |
| Discount 3 | 2.0% | £25,000+ monthly volume |

**Planning assumption for Phase 2 evaluation:** 5% commission (standard rate, conservative)

> **Note:** Using the standard 5% rate ensures robust shadow trading evaluation. In production (Phase 3+), actual commission may be 2–4% with volume-based discounts, which would improve ROI. All documents and code use 5% consistently for Phase 2.

### 6.2 Full Cost Model

| Cost Component | Estimate | Notes |
|----------------|----------|-------|
| Commission | 5.0% of net profit | Betfair's take on winning bets (standard rate) |
| Spread cost | 1.0-2.0% | Half the bid-ask spread |
| Slippage | 0.3-0.5% | Price movement during execution |
| Partial fills | 0.2-0.5% | Unfilled portion opportunity cost |
| **Total effective cost** | **6.5-8.0%** | Must beat this to profit |

### 6.3 Breakeven Calculation

**Note:** Commission is charged only on net market winnings, so the breakeven probability shifts differently at different odds levels. The precise formula is: `p_breakeven = 1 / (1 + (odds - 1) * (1 - commission_rate))`.

For a bet at odds of 2.00 (implied 50%), with 5% commission:

```
Commission-only breakeven:
  p_breakeven = 1 / (1 + 1 * 0.95) = 1/1.95 ~ 51.3%
  Commission edge requirement: +1.3 probability points

With spread + slippage + fill risk:
  Spread cost:    ~1.5%
  Slippage:       ~0.4%
  Fill risk:      ~0.3%
  Total additional: ~2.2%

Total cost hurdle (approximate): ~3.5% of stake
```

**Implication:** Only trade when exploitability score suggests meaningful structural edge. The exact cost threshold varies by odds level — a flat "X% mispricing" rule miscalibrates at extreme odds.

---

## 7. Edge Definition & Calculation

### 7.1 What Constitutes Capturable Edge

Only edges that survive **all** of the following are considered valid:

| Cost/Risk | Description |
|-----------|-------------|
| Commission | 5% of net profit (standard rate for Phase 2) |
| Spread | Entry at worse price than mid |
| Slippage | Price moves against during execution |
| Fill risk | Order may not fully execute |
| Safety margin | Buffer for estimation error |

**Theoretical value without executability is worthless.**

### 7.2 Edge Calculation Formula

```
capturable_edge = (estimated_edge - total_costs - safety_margin)

Where:
  estimated_edge    = structural inefficiency signal (from exploitability score)
  total_costs       = commission + spread + slippage + fill_risk
  safety_margin     = 1.5% (buffer for model uncertainty)

Decision rule:
  IF capturable_edge > 0 → CONSIDER trade
  IF capturable_edge ≤ 0 → NO trade
```

### 7.3 Worked Example

**Market:** Fortuna Düsseldorf vs Hannover 96 (2. Bundesliga)
**Selection:** Fortuna Düsseldorf
**Time to kickoff:** 8 hours
**Exploitability score:** 72

```
Market data:
  Back price:     2.30
  Lay price:      2.38
  Spread:         0.08 (3.5%)
  Depth at best:  £450
  Volume matched: £12,000

Estimated structural edge (from regime analysis): 4.5%

Cost breakdown:
  Spread cost:    1.75% (half of 3.5%)
  Slippage:       0.4%
  Commission:     5% × expected_profit ≈ 0.95%
  Fill risk:      0.3%
  Total costs:    3.40%

Safety margin: 1.5%

Capturable edge = 4.5% - 3.40% - 1.5% = -0.40%

Decision: NO TRADE (capturable edge negative after costs)
```

Even with a 72 exploitability score, the edge doesn't survive costs in this example. **This is expected** — most markets should result in no action.

---

## 8. Risk Management

### 8.1 Bankroll Management

| Parameter | Phase 3 | Phase 4 |
|-----------|---------|---------|
| Total bankroll | £1,000-£5,000 | £5,000-£20,000 |
| Max single bet | 2% | 2% |
| Max daily exposure | 10% | 10% |
| Max weekly exposure | 25% | 30% |
| Max per competition | 15% | 20% |

### 8.2 Staking Method

**Flat staking with Kelly-informed caps.**

```python
def calculate_stake(bankroll, probability_edge, odds, kelly_fraction=0.25):
    """
    Conservative fractional Kelly staking.

    kelly_fraction=0.25 means we bet 25% of full Kelly,
    which significantly reduces variance at cost of some EV.

    IMPORTANT: probability_edge is Δp (absolute probability difference),
    NOT the estimated_edge percentage from the exploitability score.
    See Section 8.3 for the distinction.
    """
    # Full Kelly
    p = 1 / odds + probability_edge  # estimated true probability
    q = 1 - p
    b = odds - 1
    full_kelly = (b * p - q) / b

    # Fractional Kelly with caps
    stake_fraction = full_kelly * kelly_fraction
    stake_fraction = max(0, min(stake_fraction, 0.02))  # Cap at 2%

    return bankroll * stake_fraction
```

### 8.3 Edge Definition Clarification

**CRITICAL DISTINCTION** — there are two different "edge" concepts in this strategy:

**1. estimated_edge (Section 7.2 — Capturable Edge Formula)**
This is a heuristic cost-adjusted margin derived from the exploitability score. It represents a structural market inefficiency signal as a percentage. It is used for the go/no-go trade decision. It is NOT directly additive to probability and must NOT be fed into Kelly.

**2. probability_edge / Δp (Kelly Criterion above)**
This is the absolute probability difference: `estimated_true_probability - market_implied_probability`. It is the direct input to Kelly staking. For example, if the market implies 50% and you estimate 53%, then Δp = 0.03.

**In Phase 2:** Kelly staking is DISABLED (`use_kelly=False` in config). The probability_edge definition will be refined when true probability estimation is implemented in Phase 3+. Until then, flat staking is used.

### 8.3 Drawdown Limits

| Drawdown Level | Action |
|----------------|--------|
| 10% | Review: check for regime change, reduce stake by 25% |
| 15% | Pause: stop new bets, analyse last 50 bets |
| 20% | Stop: halt all activity, full review required |
| 25% | Exit: close positions, reassess entire strategy |

### 8.4 Kill Switches

Automatic suspension triggers:

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Rolling 30-day ROI | < -5% | Pause trading, review |
| Daily loss | > 5% bankroll | Stop for day |
| Consecutive losses | 10 in a row | Pause, check execution |
| Regime instability | Score correlation < 0.3 | Pause hypothesis, investigate |
| System errors | > 5% failed executions | Halt, fix infrastructure |

### 8.5 Correlation Limits

Avoid concentration in correlated outcomes:

```
Max exposure to single event: 4% of bankroll
Max exposure to single matchday: 15% of bankroll
Max exposure to single competition per week: 20% of bankroll
```

---

## 9. Machine Learning Policy

### 9.1 Phase 1-2: No ML

Early stages rely exclusively on:

- Descriptive statistics
- Heuristic rules
- Human oversight and judgement
- Simple threshold-based scoring

**Rationale:** ML requires labelled data and stable patterns. Introducing ML too early risks:
- Overfitting to noise
- False confidence in spurious patterns
- Obscuring fundamental strategy flaws

### 9.2 Phase 3+: Evidence-Based ML Introduction

ML may be introduced **only** when:

| Prerequisite | Threshold |
|--------------|-----------|
| Labelled outcomes | 2,000+ settled bets |
| Regime stability | 6+ months of consistent patterns |
| Manual baseline | Profitable heuristics to beat |
| Clear use case | Specific problem ML solves |

### 9.3 Approved ML Applications

| Application | Purpose | Not For |
|-------------|---------|---------|
| Regime classification | Identify market state | Predicting outcomes |
| Anomaly detection | Flag unusual patterns | Generating signals |
| Score calibration | Improve exploitability estimates | Replacing human judgement |
| Execution timing | Optimise entry points | Outcome prediction |

### 9.4 Prohibited ML Applications

- **Outcome prediction** — We don't predict winners
- **Form-based models** — We don't use team/player data
- **News sentiment** — We don't parse media
- **Black-box trading** — All models must be interpretable

---

## 10. Governance & Documentation

### 10.1 Research Experiment Protocol

Every hypothesis test must follow this template:

```markdown
# Experiment: [Name]

## Hypothesis
[Clear, falsifiable statement]

## Method
- Data source:
- Time period:
- Sample size:
- Success metric:
- Statistical test:

## Results
- Primary metric:
- Statistical significance:
- Effect size:

## Decision
[ ] ADOPT - Implement in production
[ ] REJECT - Insufficient evidence
[ ] EXTEND - Need more data
[ ] MODIFY - Adjust hypothesis and retest

## Notes
[Learnings, caveats, future work]
```

### 10.2 Version Control Requirements

All of the following must be version-controlled:

| Asset | Repository | Versioning |
|-------|------------|------------|
| Configuration | Git | Semantic versioning |
| Scoring weights | Database | Timestamped versions |
| Threshold parameters | Database | Timestamped versions |
| Research notebooks | Git | Date-prefixed |
| Model artefacts | Git LFS | Model registry |

### 10.3 Change Management

```
For any parameter change:
  1. Document rationale
  2. Shadow test for minimum 1 week
  3. Compare shadow performance
  4. Peer review (even if self-review)
  5. Staged rollout (50% traffic first)
  6. Monitor for 48 hours
  7. Full rollout or rollback
```

### 10.4 Weekly Review Checklist

```markdown
## Weekly Review - [Date]

### Performance
- [ ] P&L this week: £___
- [ ] ROI this week: ___%
- [ ] Cumulative ROI: ___%
- [ ] Drawdown from peak: ___%

### Activity
- [ ] Bets placed: ___
- [ ] Win rate: ___%
- [ ] Average odds: ___
- [ ] Markets skipped (high score, no trade): ___

### System Health
- [ ] Uptime: ___%
- [ ] Data quality issues: ___
- [ ] Execution failures: ___

### Hypothesis Check
- [ ] Any hypotheses showing degradation?
- [ ] Any new opportunities identified?
- [ ] Hypothesis comparison review

### Actions
- [ ] [Action items for next week]
```

### 10.5 Multiple Testing & Hypothesis Selection

When Phase 2 concludes with multiple hypotheses tested in parallel, selection bias is a critical risk. Even with no edge, one hypothesis will look profitable by chance if enough are tested.

**Mitigation (required):**

1. **Time-split holdout** — Divide shadow data: 60% in-sample (discovery), 40% out-of-sample (validation). Pick hypotheses based on in-sample, confirm on out-of-sample. Only hypotheses with consistent performance across both periods qualify for Phase 3.

2. **Bonferroni correction** — For N concurrent hypotheses, adjust significance threshold to α / N. Example: 5 hypotheses tested simultaneously requires α = 0.01 per hypothesis instead of α = 0.05.

3. **Bias towards understatement** — Present shadow ROI conservatively. Assume closing prices are rational. Include full cost model with no discounts.

**Decision rule for Phase 3 promotion:**

```
Proceed with hypothesis H to Phase 3 ONLY if:
  1. Out-of-sample ROI > 2% (after costs at 5% commission)
  2. Average CLV > 0% (pricing skill signal)
  3. Consistent across time-split (no data-snooping bias)
  4. Win rate stable across time periods
  5. Minimum 200 out-of-sample decisions
```

---

## 11. Performance Evaluation

### 11.1 Primary Metrics

| Metric | Definition | Target |
|--------|------------|--------|
| ROI (after costs) | Net profit / total staked | >3% |
| CLV (Closing Line Value) | Entry price vs closing mid-price | >0% average (pricing skill signal) |
| Return on Risk (RoR) | Net P&L / max loss (normalised) | >0% |
| Max drawdown | Largest peak-to-trough decline | <15% |
| Sharpe ratio | Risk-adjusted return | >1.0 |
| Regime stability | Score-to-outcome correlation | >0.3 |

### 11.2 Secondary Metrics

| Metric | Definition | Purpose |
|--------|------------|---------|
| Win rate | Winning bets / total bets | Outcome hit rate |
| Yield | Net profit / number of bets | Per-bet efficiency |
| Fill rate | Executed / attempted volume | Liquidity access |
| Avg time to fill | Order placement to execution | Market impact |
| Hypothesis concentration | % volume in top 3 hypotheses | Diversification |

### 11.3 Metric Hierarchy

```
Primary goal:   Positive ROI after costs AND positive average CLV
Constraint 1:   Drawdown < 15%
Constraint 2:   Regime stability maintained
Constraint 3:   CLV consistently positive after 100+ decisions
Secondary:      Win rate, fill rates, efficiency
```

**CLV is a primary metric.** For an exchange-only programme that claims to find structural mispricing, CLV is the fastest and lowest-variance signal of genuine pricing skill. You don't need to wait for 500 match outcomes to know if you're consistently getting better prices than close.

Consistently negative CLV after 100+ decisions is a WARNING signal — it means the strategy lacks pricing skill, even if ROI is temporarily positive due to lucky outcome variance. CLV should be computed against the closing mid-price (average of closing back and lay) rather than closing back or lay separately, to avoid noise from closing spreads in thin markets.

---

## 12. Failure Criteria

This programme is **terminated** if any of the following occur:

| Criterion | Threshold | Timeframe |
|-----------|-----------|-----------|
| No stable profitable hypothesis | 0 hypotheses with >2% ROI | After 24 months |
| Costs dominate | All identified edges <5% gross | After 18 months |
| Systematic overfitting | Out-of-sample ROI <50% of in-sample | Any time |
| Manual override dependency | >30% of decisions override system | After 12 months |
| Unacceptable drawdown | >30% from peak | Any time |
| Loss of interest/commitment | Unable to maintain system | Any time |

### Failure Response Protocol

```
IF failure_criterion_met:
  1. Stop all live trading immediately
  2. Document what happened
  3. Analyse root cause
  4. Archive all data and learnings
  5. Write post-mortem
  6. Accept outcome without regret
```

**Failure is an acceptable outcome.** The goal is to *discover* whether edge exists, not to *force* edge to exist.

---

## 13. Success Criteria

The strategy is considered **successful** if:

| Criterion | Threshold | Timeframe |
|-----------|-----------|-----------|
| Long-term ROI | >3% after all costs | 24+ months |
| Drawdown control | <15% max | Sustained |
| Hypothesis repeatability | 2+ hypotheses profitable | 12+ months each |
| Operational sustainability | <5 hours/week maintenance | Sustained |
| Scalability | Can deploy £10k+ without edge degradation | Demonstrated |

### Success Response Protocol

```
IF success_criteria_met:
  1. Document the working system thoroughly
  2. Consider incremental scaling (50% increase max)
  3. Maintain discipline (no overconfidence)
  4. Continue monitoring for regime decay
  5. Explore adjacent opportunities cautiously
```

---

## 14. Personal Operating Principles

### The Five Disciplines

1. **Patience over action**
   - Most days should have zero bets
   - Waiting is a valid strategy
   - FOMO is the enemy

2. **Evidence over intuition**
   - Gut feelings are hypotheses, not facts
   - Data decides, not hope
   - Past performance is tested, not assumed

3. **Documentation over memory**
   - If it's not written down, it didn't happen
   - Future-you will thank present-you
   - Learnings compound when recorded

4. **Capital preservation over excitement**
   - Bankroll is the lifeblood
   - Small edges, small stakes
   - Survive to trade another day

5. **Adaptation over attachment**
   - Kill your darlings (retire failing hypotheses)
   - Markets evolve, strategies must too
   - Ego has no place in the P&L

### Daily Reminders

```
Before any bet:
  "Is this decision defensible with data?"
  "Would I be comfortable reviewing this in 6 months?"
  "Am I trading because there's edge, or because I want to trade?"

After any loss:
  "Was the process correct?"
  "Is this variance or signal?"
  "What would I do differently?"

After any win:
  "Was this skill or luck?"
  "Is the edge still there?"
  "Am I getting overconfident?"
```

---

## 15. Final Statement

This programme is an engineering and research exercise, not gambling.

All decisions must be defensible with data.

The market owes us nothing. Edge must be earned through rigorous analysis, validated through patient testing, and preserved through disciplined execution.

If no sustainable edge exists, the system will conclude that fact and exit with dignity. **Finding out that something doesn't work is a valid and valuable outcome.**

The journey is the data. The destination is the truth.

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| Estimated Edge | Heuristic cost-adjusted margin from exploitability score. A percentage signal of structural inefficiency. NOT directly additive to probability. |
| Probability Edge (Δp) | Absolute probability difference: estimated_true_probability - market_implied_probability. Direct input to Kelly staking. |
| Capturable Edge | Estimated edge minus all costs and safety margin. Must be positive for trade consideration. |
| Return on Risk (RoR) | Net P&L / max loss. Normalised metric that makes BACK and LAY comparable. |
| CLV | Closing Line Value — difference between entry price and closing mid-price. Primary metric for pricing skill. |
| Regime | A stable pattern of market behaviour |
| Hypothesis | A specific trading strategy being tested with defined entry criteria |
| Niche | A specific combination of competition/market/time with exploitable characteristics |
| Exploitability Score | RidgeRadar metric combining spread, volatility, depth, and volume |
| Shadow Mode | Recording hypothetical decisions without placing real bets |
| Drawdown | Decline from peak bankroll to current value |
| Slippage | Difference between intended and actual execution price |
| Steam | Price shortening (becoming shorter odds / more likely) |
| Drift | Price lengthening (becoming longer odds / less likely) |

## Appendix B: Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│                  TRADING CHECKLIST                       │
├─────────────────────────────────────────────────────────┤
│ □ Exploitability score meets hypothesis threshold?      │
│ □ Time bucket optimal (6-24h)?                          │
│ □ Sufficient depth (>£300)?                             │
│ □ Spread acceptable (<5%)?                              │
│ □ Liquidity meets hypothesis requirement?               │
│ □ Momentum criteria met (if applicable)?                │
│ □ Capturable edge positive after costs?                 │
│ □ Within daily/weekly exposure limits?                  │
│ □ No correlated open positions?                         │
│ □ System health green?                                  │
├─────────────────────────────────────────────────────────┤
│ ALL boxes checked → Proceed                             │
│ ANY box unchecked → Skip                                │
└─────────────────────────────────────────────────────────┘
```

---

*End of document.*
