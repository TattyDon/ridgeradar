-- RidgeRadar: High-Scoring Market Analysis
-- Run these queries to understand what drives good scores
--
-- Usage: psql -d ridgeradar -f scripts/analyse_high_scores.sql

-- ============================================================================
-- 1. HIGH SCORING MARKETS - RAW METRICS
-- Shows the actual metrics for markets scoring 55+
-- ============================================================================

SELECT
    c.name AS competition,
    e.name AS event,
    m.name AS market,
    es.total_score,
    es.time_bucket,
    es.odds_band,
    -- Component scores (0-100 each)
    es.spread_score,
    es.volatility_score,
    es.update_score,
    es.depth_score,
    es.volume_penalty,
    -- Raw metrics from profile
    mp.avg_spread_ticks,
    mp.price_volatility,
    mp.update_rate_per_min,
    mp.avg_depth_best,
    mp.total_matched_volume,
    mp.snapshot_count
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
    AND mp.profile_date = CURRENT_DATE
WHERE es.total_score >= 55
ORDER BY es.total_score DESC
LIMIT 50;


-- ============================================================================
-- 2. SCORE COMPONENT ANALYSIS
-- Understand which components contribute most to high scores
-- ============================================================================

SELECT
    CASE
        WHEN total_score >= 70 THEN 'Excellent (70+)'
        WHEN total_score >= 55 THEN 'High (55-70)'
        WHEN total_score >= 40 THEN 'Medium (40-55)'
        ELSE 'Low (<40)'
    END AS score_band,
    COUNT(*) AS market_count,
    ROUND(AVG(spread_score), 1) AS avg_spread_score,
    ROUND(AVG(volatility_score), 1) AS avg_volatility_score,
    ROUND(AVG(update_score), 1) AS avg_update_score,
    ROUND(AVG(depth_score), 1) AS avg_depth_score,
    ROUND(AVG(volume_penalty), 1) AS avg_volume_penalty
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
WHERE c.enabled = true
GROUP BY score_band
ORDER BY
    CASE score_band
        WHEN 'Excellent (70+)' THEN 1
        WHEN 'High (55-70)' THEN 2
        WHEN 'Medium (40-55)' THEN 3
        ELSE 4
    END;


-- ============================================================================
-- 3. RAW METRIC RANGES BY SCORE BAND
-- What are the actual spread/volatility/volume values for each score band?
-- ============================================================================

SELECT
    CASE
        WHEN es.total_score >= 70 THEN 'Excellent (70+)'
        WHEN es.total_score >= 55 THEN 'High (55-70)'
        WHEN es.total_score >= 40 THEN 'Medium (40-55)'
        ELSE 'Low (<40)'
    END AS score_band,
    COUNT(*) AS count,
    -- Spread (in ticks)
    ROUND(AVG(mp.avg_spread_ticks)::numeric, 2) AS avg_spread_ticks,
    ROUND(MIN(mp.avg_spread_ticks)::numeric, 2) AS min_spread,
    ROUND(MAX(mp.avg_spread_ticks)::numeric, 2) AS max_spread,
    -- Volatility
    ROUND(AVG(mp.price_volatility)::numeric, 4) AS avg_volatility,
    -- Update rate
    ROUND(AVG(mp.update_rate_per_min)::numeric, 2) AS avg_update_rate,
    -- Depth
    ROUND(AVG(mp.avg_depth_best)::numeric, 0) AS avg_depth,
    -- Volume
    ROUND(AVG(mp.total_matched_volume)::numeric, 0) AS avg_volume,
    ROUND(MIN(mp.total_matched_volume)::numeric, 0) AS min_volume,
    ROUND(MAX(mp.total_matched_volume)::numeric, 0) AS max_volume
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
    AND mp.profile_date = CURRENT_DATE
WHERE c.enabled = true
GROUP BY score_band
ORDER BY
    CASE score_band
        WHEN 'Excellent (70+)' THEN 1
        WHEN 'High (55-70)' THEN 2
        WHEN 'Medium (40-55)' THEN 3
        ELSE 4
    END;


-- ============================================================================
-- 4. COMPETITION LEADERBOARD
-- Which competitions produce the best scores?
-- ============================================================================

SELECT
    c.name AS competition,
    c.country_code,
    COUNT(DISTINCT es.market_id) AS markets_scored,
    ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
    ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
    COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value_markets,
    COUNT(*) FILTER (WHERE es.total_score >= 70) AS excellent_markets,
    -- Average raw metrics
    ROUND(AVG(mp.avg_spread_ticks)::numeric, 2) AS avg_spread,
    ROUND(AVG(mp.total_matched_volume)::numeric, 0) AS avg_volume
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
    AND mp.profile_date = CURRENT_DATE
WHERE c.enabled = true
GROUP BY c.id, c.name, c.country_code
HAVING COUNT(DISTINCT es.market_id) >= 5
ORDER BY AVG(es.total_score) DESC
LIMIT 25;


-- ============================================================================
-- 5. TIME BUCKET ANALYSIS
-- Which time windows produce the best scores?
-- ============================================================================

SELECT
    es.time_bucket,
    COUNT(*) AS total_scores,
    ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
    ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
    COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value,
    COUNT(*) FILTER (WHERE es.total_score >= 70) AS excellent,
    -- What percentage are high value?
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE es.total_score >= 55) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_high_value
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
WHERE c.enabled = true
GROUP BY es.time_bucket
ORDER BY
    CASE es.time_bucket
        WHEN '72h+' THEN 1
        WHEN '24-72h' THEN 2
        WHEN '6-24h' THEN 3
        WHEN '2-6h' THEN 4
        WHEN '<2h' THEN 5
        ELSE 6
    END;


-- ============================================================================
-- 6. ODDS BAND ANALYSIS
-- Which odds ranges produce the best scores?
-- ============================================================================

SELECT
    es.odds_band,
    COUNT(*) AS total_scores,
    ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
    ROUND(MAX(es.total_score)::numeric, 2) AS max_score,
    COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE es.total_score >= 55) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_high_value
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
WHERE c.enabled = true
GROUP BY es.odds_band
ORDER BY AVG(es.total_score) DESC;


-- ============================================================================
-- 7. VOLUME PENALTY EFFECTIVENESS
-- Verify that high-volume markets are scoring low
-- ============================================================================

SELECT
    CASE
        WHEN mp.total_matched_volume > 200000 THEN 'Very High (>200k)'
        WHEN mp.total_matched_volume > 100000 THEN 'High (100-200k)'
        WHEN mp.total_matched_volume > 50000 THEN 'Medium (50-100k)'
        WHEN mp.total_matched_volume > 30000 THEN 'Low-Med (30-50k)'
        ELSE 'Low (<30k)'
    END AS volume_band,
    COUNT(*) AS market_count,
    ROUND(AVG(es.total_score)::numeric, 2) AS avg_score,
    ROUND(AVG(es.volume_penalty)::numeric, 2) AS avg_volume_penalty,
    COUNT(*) FILTER (WHERE es.total_score >= 55) AS high_value
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
    AND mp.profile_date = CURRENT_DATE
WHERE c.enabled = true
GROUP BY volume_band
ORDER BY
    CASE volume_band
        WHEN 'Low (<30k)' THEN 1
        WHEN 'Low-Med (30-50k)' THEN 2
        WHEN 'Medium (50-100k)' THEN 3
        WHEN 'High (100-200k)' THEN 4
        ELSE 5
    END;


-- ============================================================================
-- 8. COPA DEL REY DEEP DIVE
-- Your top performer - what makes it special?
-- ============================================================================

SELECT
    e.name AS event,
    m.name AS market,
    es.total_score,
    es.spread_score,
    es.volatility_score,
    es.depth_score,
    es.volume_penalty,
    mp.avg_spread_ticks,
    mp.price_volatility,
    mp.avg_depth_best,
    mp.total_matched_volume,
    e.scheduled_start
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
WHERE c.name ILIKE '%Copa del Rey%'
ORDER BY es.total_score DESC
LIMIT 20;


-- ============================================================================
-- 9. LOW SCORING HIGH-VOLUME (EFFICIENT MARKETS)
-- Verify EPL/UCL-like markets are scoring low
-- ============================================================================

SELECT
    c.name AS competition,
    e.name AS event,
    es.total_score,
    es.volume_penalty,
    mp.total_matched_volume,
    mp.avg_spread_ticks
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
JOIN market_profiles_daily mp ON es.market_id = mp.market_id
WHERE mp.total_matched_volume > 100000
ORDER BY mp.total_matched_volume DESC
LIMIT 20;


-- ============================================================================
-- 10. DAILY SCORE DISTRIBUTION SUMMARY
-- Quick overview of today's scores
-- ============================================================================

SELECT
    'Today' AS period,
    COUNT(*) AS total_markets,
    COUNT(*) FILTER (WHERE total_score >= 70) AS excellent_70_plus,
    COUNT(*) FILTER (WHERE total_score >= 55 AND total_score < 70) AS high_55_70,
    COUNT(*) FILTER (WHERE total_score >= 40 AND total_score < 55) AS medium_40_55,
    COUNT(*) FILTER (WHERE total_score < 40) AS low_under_40,
    ROUND(AVG(total_score)::numeric, 2) AS overall_avg_score,
    ROUND(MAX(total_score)::numeric, 2) AS highest_score
FROM exploitability_scores es
JOIN markets m ON es.market_id = m.id
JOIN events e ON m.event_id = e.id
JOIN competitions c ON e.competition_id = c.id
WHERE c.enabled = true;
