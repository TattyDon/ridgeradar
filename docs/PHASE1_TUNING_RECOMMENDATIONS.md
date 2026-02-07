# RidgeRadar Phase 1: Tuning Recommendations

**Date:** 2026-02-05
**Data Collection Period:** < 24 hours
**Total Markets Scored:** 128,532

---

## Current State Summary

### Score Distribution

| Category | Count | Percentage |
|----------|-------|------------|
| High (70+) | 11 | 0.009% |
| Medium (50-70) | 485 | 0.38% |
| Low (<50) | 128,036 | 99.6% |

### Top Performing Competitions

| Rank | Competition | Avg Score | Max Score | High Value (55+) |
|------|-------------|-----------|-----------|------------------|
| 1 | UEFA Europa Conference League | 16.6 | 62.0 | 65 |
| 2 | French Ligue 2 | 16.1 | 59.9 | 63 |
| 3 | Spanish Copa del Rey | 16.0 | **73.0** | 29 |
| 4 | Qatari Stars League | 14.3 | 56.7 | 5 |
| 5 | Albanian Superliga | 12.0 | 57.8 | 5 |

**Key Finding:** Spanish Copa del Rey produces the highest individual scores (73.0), with 5 markets scoring 70+. This is exactly the kind of opportunity the system is designed to find.

---

## Issue 1: Duplicate Rows in Market Radar

### Problem
The same market appears multiple times because the scoring task creates a new `ExploitabilityScore` record every 5 minutes, rather than updating the existing one.

### Solution

**Option A: Fix the Query (Quick Win)**

Update `/app/api/routes/scores.py` to return only the latest score per market:

```python
from sqlalchemy import distinct

# In list_scores():
query = (
    select(ExploitabilityScore, Market, Event, Competition)
    .distinct(ExploitabilityScore.market_id)  # One per market
    .join(Market, ExploitabilityScore.market_id == Market.id)
    .join(Event, Market.event_id == Event.id)
    .join(Competition, Event.competition_id == Competition.id)
    .where(
        Competition.enabled == True,
        ExploitabilityScore.total_score >= min_score,
    )
    .order_by(
        ExploitabilityScore.market_id,
        ExploitabilityScore.scored_at.desc()  # Latest first
    )
)
```

**Option B: Use Upsert in Scoring Task (Better Long-term)**

Update `/app/tasks/scoring.py` to use `INSERT ... ON CONFLICT UPDATE`:

```python
from sqlalchemy.dialects.postgresql import insert

# Instead of session.add(score), use upsert
stmt = insert(ExploitabilityScore).values(
    market_id=market.id,
    time_bucket=profile.time_bucket,
    scored_at=datetime.now(timezone.utc),
    # ... other fields
).on_conflict_do_update(
    index_elements=['market_id', 'time_bucket'],
    set_={
        'scored_at': datetime.now(timezone.utc),
        'total_score': result.total_score,
        # ... update other fields
    }
)
await session.execute(stmt)
```

This requires adding a unique constraint:
```sql
ALTER TABLE exploitability_scores
ADD CONSTRAINT unique_market_bucket
UNIQUE (market_id, time_bucket);
```

### Recommendation
Implement **Option A** immediately for UI fix, then **Option B** to reduce database bloat.

---

## Issue 2: Score Distribution Analysis

### Is 99.6% Low Scores a Problem?

**No, this is by design.** The system should be highly selective. Most markets ARE efficient and SHOULD score low.

However, the average scores (~14-17) seem quite low even for the best competitions. Let's analyse why.

### Hypothesis: Tight Spreads Dominate

The spread scoring function:
```python
if spread_ticks < min_ticks:  # min_ticks = 2
    return spread_ticks / min_ticks * 0.3  # Max 30% score
```

If most markets have 1-2 tick spreads, they're capped at 30% on the spread component (worth 25% of total = max 7.5 points from spread).

### Hypothesis: Low Volatility

The volatility function targets 4% volatility. Most stable markets might have 1-2% volatility, giving them ~25-50% on volatility (worth 25% of total = 6-12 points).

### Suggested Tuning Experiments

**Experiment 1: Lower the volatility target**
```yaml
volatility:
  target: 0.02  # Was 0.04 - try halving it
  max: 0.08     # Was 0.12
```

**Experiment 2: Lower the spread sweet spot**
```yaml
spread:
  min_ticks: 1       # Was 2
  sweet_spot_max: 5  # Was 8
  max_ticks: 10      # Was 12
```

**Experiment 3: Lower depth expectations**
```yaml
depth:
  min: 100       # Was 150
  optimal: 800   # Was 1500
  max: 5000      # Was 8000
```

### Testing Approach

Before changing production config:

1. **Extract sample data** from current high-scoring markets:
   ```sql
   SELECT
     es.total_score,
     mp.avg_spread_ticks,
     mp.price_volatility,
     mp.update_rate_per_min,
     mp.avg_depth_best,
     mp.total_matched_volume
   FROM exploitability_scores es
   JOIN market_profiles_daily mp ON es.market_id = mp.market_id
   WHERE es.total_score > 55
   ORDER BY es.total_score DESC
   LIMIT 50;
   ```

2. **Run scoring simulations** with different configs on the same data

3. **Compare score distributions** before/after

---

## Issue 3: Copa del Rey Deep Dive

### Why Copa del Rey Scores Well

| Factor | Value | Scoring Impact |
|--------|-------|----------------|
| Volume | £12-20k | No penalty (below £30k threshold) |
| Spreads | 3-6 ticks | Sweet spot (100% spread score) |
| Depth | £400-800 | Adequate (good depth score) |
| Volatility | 3-5% | Near target (good volatility score) |

### What This Tells Us

Copa del Rey cup matches often feature:
- Lower-division teams (less efficient markets)
- Moderate but not excessive liquidity
- Active trading but not saturated

**This validates the scoring philosophy.** The system IS finding structural inefficiencies.

### Similar Competitions to Watch

Based on similar characteristics, likely high-value competitions:
- Domestic cup competitions (FA Cup early rounds, DFB-Pokal)
- UEFA Conference League (already scoring well)
- Lower divisions with decent liquidity (Ligue 2, Championship, Serie B)

---

## Recommended Actions

### Immediate (Today)

1. **Fix duplicate rows** in UI using query deduplication
2. **Extract raw metrics** from high-scoring markets to understand what drives good scores
3. **Document findings** in a research log

### This Week

4. **Run tuning experiments** on volatility and spread thresholds
5. **Add runner-level scoring** if not already implemented (scores per selection, not just per market)
6. **Implement score history chart** on market detail page

### Next Phase

7. **Begin shadow trading** on markets scoring 65+
8. **Track outcomes** to validate score correlation with exploitability
9. **Build competition ranking dashboard** to identify best leagues over time

---

## Metrics to Track

| Metric | Current | Target | Notes |
|--------|---------|--------|-------|
| Markets 70+ | 11 | 50+ | Need more high-scoring markets for shadow testing |
| Markets 55+ | ~500 | 1000+ | Healthy pipeline for analysis |
| Avg score (top comp) | 16 | 25-35 | Tuning might improve this |
| Data freshness | <24h | 7+ days | Need more history for reliable stats |

---

## Configuration Change Log

| Date | Change | Rationale | Result |
|------|--------|-----------|--------|
| 2026-02-04 | Initial config | Spec defaults | Baseline |
| | | | |

*(Record all config changes here)*

---

## Next Review

Schedule review after **7 days** of data collection to:
- Assess score stability over time
- Identify if Copa del Rey pattern holds
- Determine if tuning is needed
- Begin shadow trading preparation
