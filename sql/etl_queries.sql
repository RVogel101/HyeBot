-- ============================================================================
-- Hye-tasion ETL & Analytics Queries for SQLite
-- Database: hye_tasion.db
-- ============================================================================

-- ========================
-- 1. EXTRACT — Overview
-- ========================

-- Total articles by source
SELECT s.name AS source_name, s.category, s.is_active,
       COUNT(a.id) AS article_count,
       MAX(a.scraped_at) AS last_scraped
FROM sources s
LEFT JOIN articles a ON a.source_id = s.id
GROUP BY s.id
ORDER BY article_count DESC;

-- Articles scraped today
SELECT s.name, a.title, a.published_at, a.category, a.tags
FROM articles a
JOIN sources s ON s.id = a.source_id
WHERE DATE(a.scraped_at) = DATE('now')
ORDER BY a.scraped_at DESC;

-- International (keyword-filtered) source yield
SELECT s.name, s.category, COUNT(a.id) AS articles_found
FROM sources s
LEFT JOIN articles a ON a.source_id = s.id
WHERE s.category = 'international'
GROUP BY s.id
ORDER BY articles_found DESC;

-- Articles per category
SELECT a.category, COUNT(*) AS total
FROM articles a
GROUP BY a.category
ORDER BY total DESC;

-- ========================
-- 2. TRANSFORM — Tagging & Classification
-- ========================

-- Flag unprocessed articles (ready for post idea generation)
SELECT id, title, summary, category,
       CASE
           WHEN title LIKE '%genocide%' OR title LIKE '%1915%' THEN 'genocide_remembrance'
           WHEN title LIKE '%Karabakh%' OR title LIKE '%Artsakh%' THEN 'artsakh_conflict'
           WHEN title LIKE '%diaspora%' THEN 'diaspora_community'
           WHEN title LIKE '%Pashinyan%' OR title LIKE '%parliament%' THEN 'politics'
           WHEN title LIKE '%Yerevan%' AND (title LIKE '%culture%' OR title LIKE '%music%' OR title LIKE '%art%') THEN 'culture'
           ELSE 'general'
       END AS topic_tag
FROM articles
WHERE is_processed = 0
ORDER BY published_at DESC;

-- Mark articles as processed after generating post ideas
-- UPDATE articles SET is_processed = 1 WHERE id IN (...);

-- Deduplicate articles with similar titles from different sources
SELECT a1.id AS dup_id, a1.title, s1.name AS source1,
       a2.id AS original_id, a2.title, s2.name AS source2
FROM articles a1
JOIN articles a2 ON a1.id > a2.id
    AND a1.title = a2.title
JOIN sources s1 ON s1.id = a1.source_id
JOIN sources s2 ON s2.id = a2.source_id;

-- ========================
-- 3. LOAD / SUMMARY — Dashboard Metrics
-- ========================

-- Daily scrape summary
SELECT DATE(scraped_at) AS scrape_date,
       COUNT(*) AS total_articles,
       COUNT(DISTINCT source_id) AS sources_active,
       SUM(CASE WHEN is_processed = 1 THEN 1 ELSE 0 END) AS processed,
       SUM(CASE WHEN is_processed = 0 THEN 1 ELSE 0 END) AS pending
FROM articles
GROUP BY DATE(scraped_at)
ORDER BY scrape_date DESC
LIMIT 30;

-- Post ideas pipeline status
SELECT status, COUNT(*) AS count
FROM post_ideas
GROUP BY status;

-- Post ideas with their source articles
SELECT pi.id, pi.title AS post_title, pi.status, pi.target_subreddit,
       pi.generation_method, pi.predicted_engagement_score,
       a.title AS article_title, s.name AS source_name
FROM post_ideas pi
LEFT JOIN articles a ON a.id = pi.article_id
LEFT JOIN sources s ON s.id = a.source_id
ORDER BY pi.generated_at DESC
LIMIT 50;

-- ========================
-- 4. REDDIT ENGAGEMENT ANALYSIS
-- ========================

-- Top performing posts by subreddit
SELECT subreddit, title, score, num_comments, upvote_ratio,
       engagement_score, post_type, created_utc
FROM reddit_posts
ORDER BY engagement_score DESC
LIMIT 25;

-- Engagement patterns — what works?
SELECT subreddit, pattern_type, pattern_value,
       avg_score, sample_count
FROM engagement_patterns
ORDER BY avg_score DESC
LIMIT 30;

-- Average engagement by subreddit
SELECT subreddit,
       COUNT(*) AS posts_analyzed,
       ROUND(AVG(score), 1) AS avg_score,
       ROUND(AVG(num_comments), 1) AS avg_comments,
       ROUND(AVG(upvote_ratio), 3) AS avg_upvote_ratio,
       ROUND(AVG(engagement_score), 2) AS avg_engagement
FROM reddit_posts
GROUP BY subreddit
ORDER BY avg_engagement DESC;

-- Title features that drive engagement
SELECT has_question, has_numbers,
       COUNT(*) AS count,
       ROUND(AVG(score), 1) AS avg_score,
       ROUND(AVG(num_comments), 1) AS avg_comments
FROM reddit_posts
GROUP BY has_question, has_numbers;

-- Optimal title length buckets
SELECT CASE
           WHEN title_length < 50 THEN 'short (<50)'
           WHEN title_length BETWEEN 50 AND 100 THEN 'medium (50-100)'
           WHEN title_length BETWEEN 101 AND 200 THEN 'long (101-200)'
           ELSE 'very long (200+)'
       END AS length_bucket,
       COUNT(*) AS count,
       ROUND(AVG(engagement_score), 2) AS avg_engagement
FROM reddit_posts
WHERE title_length IS NOT NULL
GROUP BY length_bucket
ORDER BY avg_engagement DESC;

-- ========================
-- 5. A/B TESTING RESULTS
-- ========================

-- Active A/B tests with variant performance
SELECT t.name AS test_name, t.subreddit, t.is_active,
       v.variant_label, v.title, v.title_strategy,
       v.score, v.num_comments, v.upvote_ratio, v.engagement_rate,
       v.status
FROM ab_tests t
JOIN ab_variants v ON v.test_id = t.id
ORDER BY t.created_at DESC, v.variant_label;

-- Concluded tests with winners
SELECT t.name, t.subreddit, t.p_value,
       v.variant_label AS winner, v.title AS winning_title,
       v.title_strategy AS winning_strategy,
       v.score AS final_score
FROM ab_tests t
JOIN ab_variants v ON v.id = t.winner_variant_id
WHERE t.significance_achieved = 1
ORDER BY t.concluded_at DESC;

-- Post performance timeline (score progression)
SELECT pp.reddit_post_id, pi.title,
       pp.score_at_1h, pp.score_at_6h, pp.score_at_24h, pp.score_at_7d,
       pp.final_score, pp.final_comments, pp.final_upvote_ratio
FROM post_performance pp
JOIN post_ideas pi ON pi.id = pp.post_idea_id
ORDER BY pp.created_at DESC;

-- ========================
-- 6. DATA QUALITY & MAINTENANCE
-- ========================

-- Sources that haven't been scraped recently
SELECT name, category, last_scraped_at,
       ROUND(JULIANDAY('now') - JULIANDAY(last_scraped_at), 1) AS days_stale
FROM sources
WHERE is_active = 1
  AND (last_scraped_at IS NULL
       OR JULIANDAY('now') - JULIANDAY(last_scraped_at) > 1)
ORDER BY days_stale DESC;

-- Articles missing key fields
SELECT id, title, source_id,
       CASE WHEN content IS NULL OR content = '' THEN 'no_content' ELSE 'ok' END AS content_status,
       CASE WHEN summary IS NULL OR summary = '' THEN 'no_summary' ELSE 'ok' END AS summary_status,
       CASE WHEN published_at IS NULL THEN 'no_date' ELSE 'ok' END AS date_status
FROM articles
WHERE content IS NULL OR content = ''
   OR summary IS NULL OR summary = ''
   OR published_at IS NULL
LIMIT 50;

-- Orphaned post ideas (article deleted)
SELECT pi.id, pi.title, pi.article_id
FROM post_ideas pi
LEFT JOIN articles a ON a.id = pi.article_id
WHERE pi.article_id IS NOT NULL AND a.id IS NULL;

-- Database size (row counts)
SELECT 'sources' AS tbl, COUNT(*) AS rows FROM sources
UNION ALL SELECT 'articles', COUNT(*) FROM articles
UNION ALL SELECT 'post_ideas', COUNT(*) FROM post_ideas
UNION ALL SELECT 'reddit_posts', COUNT(*) FROM reddit_posts
UNION ALL SELECT 'engagement_patterns', COUNT(*) FROM engagement_patterns
UNION ALL SELECT 'ab_tests', COUNT(*) FROM ab_tests
UNION ALL SELECT 'ab_variants', COUNT(*) FROM ab_variants
UNION ALL SELECT 'post_performance', COUNT(*) FROM post_performance;
