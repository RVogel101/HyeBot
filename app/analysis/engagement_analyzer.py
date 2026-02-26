"""
Engagement analyzer — mines the stored Reddit posts to identify patterns
that correlate with high engagement, then surfaces those patterns as
recommendations for post generation.
"""
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

from app.models.reddit_data import RedditPost, EngagementPattern

logger = logging.getLogger(__name__)

# ─── Thresholds ────────────────────────────────────────────────────────────────
HIGH_ENGAGEMENT_PERCENTILE = 75       # Posts in top 25 % score
MIN_POSTS_FOR_PATTERN = 5            # Minimum samples to derive a pattern


def _posts_to_df(posts: list[RedditPost]) -> pd.DataFrame:
    # coerce potential Column objects to plain types before calculations
    rows = []
    for p in posts:
        title = str(p.title or "")
        rows.append({
            "id": p.id,
            "subreddit": str(p.subreddit or ""),
            "title": title,
            "score": p.score,
            "upvote_ratio": p.upvote_ratio,
            "num_comments": p.num_comments,
            "title_length": p.title_length or len(title),
            "title_word_count": p.title_word_count or len(title.split()),
            "has_question": bool(p.has_question),
            "has_numbers": bool(p.has_numbers),
            "sentiment_score": p.sentiment_score or 0.0,
            "post_type": p.post_type or "link",
            "flair": p.flair or "",
            "engagement_score": p.engagement_score or p.score,
            "created_utc": p.created_utc,
        })
    return pd.DataFrame(rows)


def _title_structure(title: str) -> str:
    """Classify a post title into a structural pattern."""
    t = title.strip()
    if t.endswith("?"):
        return "question"
    if re.match(r"^\d", t):
        return "starts_with_number"
    if re.search(r"\b(breaking|update|just in)\b", t, re.I):
        return "breaking_news"
    if re.search(r":\s", t):
        return "topic_colon_detail"
    if re.search(r"\b(why|how|what|who|when|where)\b", t, re.I):
        return "wh_question"
    if len(t.split()) <= 6:
        return "short_punchy"
    if len(t.split()) >= 20:
        return "long_descriptive"
    return "standard"


def analyze_engagement_patterns(db: Session, subreddit: Optional[str] = None) -> dict[str, Any]:
    """
    Run full engagement analysis across stored Reddit posts.
    Persists EngagementPattern rows to DB and returns a summary dict.
    """
    query = db.query(RedditPost)
    if subreddit:
        query = query.filter_by(subreddit=subreddit)
    posts = query.all()

    if len(posts) < 10:
        return {"error": "Not enough data — collect Reddit posts first.", "count": len(posts)}

    df = _posts_to_df(posts)
    results: dict[str, Any] = {}

    for sub in df["subreddit"].unique():
        sub_df = df[df["subreddit"] == sub].copy()
        if len(sub_df) < MIN_POSTS_FOR_PATTERN:
            continue

        threshold = np.percentile(sub_df["score"], HIGH_ENGAGEMENT_PERCENTILE)
        high = sub_df[sub_df["score"] >= threshold]
        low = sub_df[sub_df["score"] < threshold]

        sub_results: dict[str, Any] = {
            "total_posts": len(sub_df),
            "high_engagement_count": len(high),
            "score_threshold": float(threshold),
            "patterns": {},
        }

        # ── Title structure ────────────────────────────────────────────────
        high["structure"] = high["title"].apply(_title_structure)
        structure_counts = high["structure"].value_counts().to_dict()
        sub_results["patterns"]["title_structure"] = structure_counts
        _upsert_pattern(db, sub, "title_structure", structure_counts, high, threshold)

        # ── Title length buckets ──────────────────────────────────────────
        high["len_bucket"] = pd.cut(
            high["title_word_count"],
            bins=[0, 5, 10, 15, 20, 100],
            labels=["1-5w", "6-10w", "11-15w", "16-20w", "20+w"]
        ).astype(str)
        length_scores = high.groupby("len_bucket")["score"].mean().to_dict()
        sub_results["patterns"]["optimal_title_length"] = length_scores
        for bucket, avg_score in length_scores.items():
            _upsert_single_pattern(db, sub, "title_length_bucket", bucket, avg_score, len(high))

        # ── Question vs statement ──────────────────────────────────────────
        q_score = float(high[high["has_question"]]["score"].mean()) if high["has_question"].any() else 0
        s_score = float(high[~high["has_question"]]["score"].mean()) if (~high["has_question"]).any() else 0
        sub_results["patterns"]["question_avg_score"] = q_score
        sub_results["patterns"]["statement_avg_score"] = s_score

        # ── Post type ─────────────────────────────────────────────────────
        type_scores = high.groupby("post_type")["score"].mean().to_dict()
        sub_results["patterns"]["post_type_scores"] = type_scores
        for pt, avg_score in type_scores.items():
            _upsert_single_pattern(db, sub, "post_type", pt, avg_score, len(high))

        # ── Sentiment ─────────────────────────────────────────────────────
        sub_results["patterns"]["avg_sentiment_high_eng"] = float(high["sentiment_score"].mean())
        sub_results["patterns"]["avg_sentiment_low_eng"] = float(low["sentiment_score"].mean() if len(low) else 0)

        # ── Top keywords in high-engagement titles ────────────────────────
        all_words = " ".join(high["title"].tolist()).lower()
        words = re.findall(r"\b[a-z]{4,}\b", all_words)
        stop = {"that", "this", "with", "from", "have", "will", "been", "they",
                "their", "about", "were", "your", "more", "what", "when", "which"}
        top_keywords = Counter(w for w in words if w not in stop).most_common(20)
        sub_results["patterns"]["top_keywords"] = dict(top_keywords)
        for word, count in top_keywords[:10]:
            _upsert_single_pattern(db, sub, "keyword", word, count, len(high))

        # ── Posting hour (UTC) ────────────────────────────────────────────
        if "created_utc" in high.columns and high["created_utc"].notna().any():
            high = high.copy()
            high["hour"] = pd.to_datetime(high["created_utc"]).dt.hour
            hour_scores = high.groupby("hour")["score"].mean().to_dict()
            best_hours = sorted(hour_scores, key=hour_scores.get, reverse=True)[:5]
            sub_results["patterns"]["best_posting_hours_utc"] = best_hours
            for h in best_hours:
                _upsert_single_pattern(db, sub, "posting_hour_utc", str(h), hour_scores[h], len(high))

        results[sub] = sub_results
        logger.info(f"[Analyzer] r/{sub}: patterns extracted from {len(high)} high-eng posts.")

    db.commit()
    return results


def _upsert_pattern(db: Session, subreddit: str, ptype: str, counts: dict, high_df, threshold):
    for val, cnt in counts.items():
        avg_score = float(high_df[high_df["title"].apply(_title_structure) == val]["score"].mean()) if cnt else 0
        _upsert_single_pattern(db, subreddit, ptype, val, avg_score, cnt)


def _upsert_single_pattern(db: Session, subreddit: str, ptype: str, value: str, avg_score: float, count: int):
    from datetime import datetime, UTC as _UTC
    existing = db.query(EngagementPattern).filter_by(
        subreddit=subreddit, pattern_type=ptype, pattern_value=str(value)
    ).first()
    if existing:
        existing.avg_score = avg_score  # type: ignore[assignment]
        existing.sample_count = count  # type: ignore[assignment]
        existing.last_updated = datetime.now(_UTC)  # type: ignore[assignment]
    else:
        db.add(EngagementPattern(
            subreddit=subreddit,
            pattern_type=ptype,
            pattern_value=str(value),
            avg_score=avg_score,
            sample_count=count,
        ))


def get_recommendations(db: Session, subreddit: str) -> dict:
    """Return actionable recommendations for the given subreddit."""
    patterns = db.query(EngagementPattern).filter_by(subreddit=subreddit).all()
    if not patterns:
        return {"message": "No patterns yet. Run Reddit data collection first."}

    recs: dict[str, Any] = {"subreddit": subreddit, "recommendations": []}
    by_type = defaultdict(list)
    for p in patterns:
        by_type[p.pattern_type].append((p.pattern_value, p.avg_score, p.sample_count))

    if "title_structure" in by_type:
        best = max(by_type["title_structure"], key=lambda x: x[1])
        recs["recommendations"].append({
            "type": "title_structure",
            "advice": f"Use '{best[0]}' style titles — avg score {best[1]:.0f}",
            "value": best[0],
        })

    if "title_length_bucket" in by_type:
        best = max(by_type["title_length_bucket"], key=lambda x: x[1])
        recs["recommendations"].append({
            "type": "title_length",
            "advice": f"Target {best[0]} words in your title — avg score {best[1]:.0f}",
            "value": best[0],
        })

    if "keyword" in by_type:
        top_kws = sorted(by_type["keyword"], key=lambda x: x[1], reverse=True)[:10]
        recs["recommendations"].append({
            "type": "keywords",
            "advice": "High-engagement keywords to weave into titles/text",
            "value": [k[0] for k in top_kws],
        })

    if "posting_hour_utc" in by_type:
        best_hour = max(by_type["posting_hour_utc"], key=lambda x: x[1])
        recs["recommendations"].append({
            "type": "posting_time",
            "advice": f"Best UTC posting hour: {best_hour[0]}:00 — avg score {best_hour[1]:.0f}",
            "value": best_hour[0],
        })

    return recs
