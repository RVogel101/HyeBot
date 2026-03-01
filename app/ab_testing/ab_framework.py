"""
A/B testing framework.
Handles creating tests with multiple title variants, posting them to Reddit,
tracking their performance, and running statistical significance tests.
"""
import logging
import os
import time
from datetime import datetime, UTC, timedelta
from typing import Optional

import praw
from scipy import stats
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ab_test import ABTest, ABVariant, PostPerformance
from app.models.post import PostIdea, PostStatus
from app.analysis.post_generator import generate_ab_variants

logger = logging.getLogger(__name__)

# Spam-prevention settings (Reddit Developer Terms compliance)
POSTING_COOLDOWN_SECONDS = int(os.getenv("POSTING_COOLDOWN_SECONDS", "600"))
DAILY_POST_LIMIT = int(os.getenv("DAILY_POST_LIMIT", "5"))


def _get_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "script:HyeTasion:1.0 (by /u/unknown)"),
    )


def _check_posting_allowed(db: Session, subreddit: str) -> tuple[bool, str]:
    """
    Enforce posting cooldown and daily limit per subreddit.
    Returns (allowed, reason) — required by Reddit Developer Terms (no spam).
    """
    now = datetime.now(UTC)

    # Check cooldown: most recent post to this subreddit
    last_post = (
        db.query(PostIdea)
        .filter(
            PostIdea.target_subreddit == subreddit,
            PostIdea.posted_at.isnot(None),
        )
        .order_by(PostIdea.posted_at.desc())
        .first()
    )
    if last_post and last_post.posted_at is not None:
        elapsed = (now - last_post.posted_at).total_seconds()
        if elapsed < POSTING_COOLDOWN_SECONDS:
            remaining = int(POSTING_COOLDOWN_SECONDS - elapsed)
            return False, f"Posting cooldown: wait {remaining}s before posting to r/{subreddit} again."

    # Check daily limit
    day_start = now - timedelta(hours=24)
    posts_today = (
        db.query(func.count(PostIdea.id))
        .filter(
            PostIdea.target_subreddit == subreddit,
            PostIdea.posted_at > day_start,
        )
        .scalar()
    ) or 0
    if posts_today >= DAILY_POST_LIMIT:
        return False, f"Daily limit reached: {posts_today}/{DAILY_POST_LIMIT} posts to r/{subreddit} today."

    return True, ""


# ─── Test creation ─────────────────────────────────────────────────────────────

def create_ab_test(
    db: Session,
    post_idea: PostIdea,
    num_variants: int = 2,
    test_name: Optional[str] = None,
) -> ABTest:
    """
    Create an ABTest with N variants for a given PostIdea.
    Variants are stored as ABVariant rows but not yet posted.
    """
    name = test_name or f"AB Test — {post_idea.title[:60]}"
    test = ABTest(
        name=name,
        description=f"Auto-generated A/B test for post idea #{post_idea.id}",
        subreddit=post_idea.target_subreddit,
    )
    db.add(test)
    db.flush()  # get test.id

    variant_data = generate_ab_variants(db, post_idea, num_variants=num_variants)
    for vd in variant_data:
        variant = ABVariant(
            test_id=test.id,
            post_idea_id=post_idea.id,
            variant_label=vd["label"],
            title=vd["title"],
            body=vd.get("body", ""),
            title_strategy=vd.get("title_strategy", "standard"),
        )
        db.add(variant)

    db.commit()
    db.refresh(test)
    logger.info(f"[A/B] Created test #{test.id} with {len(variant_data)} variants.")
    return test


# ─── Posting variants ──────────────────────────────────────────────────────────

def post_variant_to_reddit(
    db: Session,
    variant: ABVariant,
) -> bool:
    """
    Post a single ABVariant to Reddit.
    Updates the variant with the Reddit post ID on success.
    """
    post_idea = db.query(PostIdea).filter_by(id=variant.post_idea_id).first()
    if not post_idea:
        logger.error(f"[A/B] PostIdea #{variant.post_idea_id} not found.")
        return False

    # Spam prevention: check cooldown and daily limit
    subreddit_name = str(post_idea.target_subreddit) if post_idea.target_subreddit is not None else ""
    allowed, reason = _check_posting_allowed(db, subreddit_name)
    if not allowed:
        logger.warning(f"[A/B] Posting blocked: {reason}")
        return False

    try:
        reddit = _get_reddit_client()
        # ensure plain strings are passed to PRAW
        subreddit = reddit.subreddit(subreddit_name)

        post_type: str = str(post_idea.post_type) if post_idea.post_type is not None else ""
        source_url: Optional[str] = str(post_idea.source_url) if post_idea.source_url is not None else None

        if post_type == "link" and source_url:
            submission = subreddit.submit(
                title=str(variant.title),
                url=source_url,
            )
        else:
            submission = subreddit.submit(
                title=str(variant.title),
                selftext=str(variant.body) if variant.body is not None else "",
            )

        variant.reddit_post_id = submission.id  # type: ignore[assignment]
        variant.posted_at = datetime.now(UTC)  # type: ignore[assignment]
        variant.status = "live"  # type: ignore[assignment]
        db.commit()
        logger.info(f"[A/B] Posted variant {variant.variant_label} → reddit ID {submission.id}")
        return True

    except Exception as exc:
        logger.error(f"[A/B] Failed to post variant {variant.id}: {exc}", exc_info=True)
        return False


def post_idea_to_reddit(db: Session, post_idea: PostIdea) -> bool:
    """
    Post a directly-approved PostIdea (not A/B tested) to Reddit.
    """
    # Spam prevention: check cooldown and daily limit
    subreddit_name = str(post_idea.target_subreddit) if post_idea.target_subreddit is not None else ""
    allowed, reason = _check_posting_allowed(db, subreddit_name)
    if not allowed:
        logger.warning(f"[Post] Posting blocked: {reason}")
        return False

    try:
        reddit = _get_reddit_client()
        subreddit = reddit.subreddit(subreddit_name)

        post_type: str = str(post_idea.post_type) if post_idea.post_type is not None else ""
        source_url: Optional[str] = str(post_idea.source_url) if post_idea.source_url is not None else None

        if post_type == "link" and source_url:
            submission = subreddit.submit(
                title=str(post_idea.title),
                url=source_url,
            )
        else:
            submission = subreddit.submit(
                title=str(post_idea.title),
                selftext=str(post_idea.body) if post_idea.body is not None else "",
            )

        post_idea.reddit_post_id = submission.id  # type: ignore[assignment]
        post_idea.posted_at = datetime.now(UTC)  # type: ignore[assignment]
        post_idea.status = PostStatus.posted  # type: ignore[assignment]

        # Create performance tracking row
        perf = PostPerformance(
            post_idea_id=post_idea.id,
            reddit_post_id=submission.id,
            subreddit=post_idea.target_subreddit,
            first_checked_at=datetime.now(UTC),
        )
        db.add(perf)
        db.commit()
        logger.info(f"[Post] Posted idea #{post_idea.id} → reddit ID {submission.id}")
        return True

    except Exception as exc:
        db.rollback()
        post_idea.status = PostStatus.failed  # type: ignore[assignment]
        db.commit()
        logger.error(f"[Post] Failed to post idea #{post_idea.id}: {exc}", exc_info=True)
        return False


# ─── Metrics refresh ───────────────────────────────────────────────────────────

def refresh_variant_metrics(db: Session, test: ABTest) -> None:
    """
    Fetch current Reddit metrics for all live variants in a test
    and update the database.
    """
    reddit = _get_reddit_client()
    for variant in test.variants:
        if variant.status != "live" or variant.reddit_post_id is None:
            continue
        try:
            submission = reddit.submission(id=variant.reddit_post_id)
            variant.score = submission.score
            variant.upvote_ratio = submission.upvote_ratio
            variant.num_comments = submission.num_comments
            variant.engagement_rate = submission.score * submission.upvote_ratio
            variant.last_metrics_update = datetime.now(UTC)
            logger.info(
                f"[A/B] Variant {variant.variant_label} metrics: "
                f"score={submission.score}, comments={submission.num_comments}"
            )
        except Exception as exc:
            logger.warning(f"[A/B] Metrics fetch failed for variant {variant.id}: {exc}")
    db.commit()


def refresh_post_performance(db: Session, reddit_post_id: str) -> Optional[PostPerformance]:
    """Refresh performance metrics for a directly-posted idea."""
    perf = db.query(PostPerformance).filter_by(reddit_post_id=reddit_post_id).first()
    if not perf:
        return None
    try:
        reddit = _get_reddit_client()
        submission = reddit.submission(id=reddit_post_id)
        now = datetime.now(UTC)

        if perf.first_checked_at is not None:
            elapsed_hours = (now - perf.first_checked_at).total_seconds() / 3600

            # Fill the most recent applicable bucket that hasn't been set yet.
            # Buckets: 1h, 2h, 4h, 6h, 12h, 24h, 48h, 7d
            buckets: list[tuple[float, str]] = [
                (1.5,  "score_at_1h"),
                (3.0,  "score_at_2h"),
                (5.0,  "score_at_4h"),
                (9.0,  "score_at_6h"),
                (18.0, "score_at_12h"),
                (36.0, "score_at_24h"),
                (72.0, "score_at_48h"),
            ]
            for threshold, attr in buckets:
                if elapsed_hours < threshold and getattr(perf, attr) is None:
                    setattr(perf, attr, submission.score)
                    break
            else:
                # Past 72 h → final / 7d bucket
                if perf.score_at_7d is None or elapsed_hours >= 168:
                    perf.score_at_7d = submission.score  # type: ignore[assignment]
                perf.final_score = submission.score  # type: ignore[assignment]
                perf.final_comments = submission.num_comments  # type: ignore[assignment]
                perf.final_upvote_ratio = submission.upvote_ratio  # type: ignore[assignment]

        perf.last_checked_at = now  # type: ignore[assignment]
        db.commit()
    except Exception as exc:
        logger.warning(f"[Performance] Metrics refresh failed: {exc}")
    return perf


# ─── Statistical analysis ──────────────────────────────────────────────────────

def _build_metric_vector(variant: ABVariant) -> list[float]:
    """
    Build a normalised metric vector from a variant's Reddit metrics.
    Each metric is treated as an independent observation so we can run
    a proper statistical test even with single-snapshot data.
    """
    metrics: list[float] = []
    if variant.score is not None:
        metrics.append(float(variant.score))
    if variant.num_comments is not None:
        metrics.append(float(variant.num_comments))
    if variant.upvote_ratio is not None:
        # Scale upvote_ratio (0-1) into the same order of magnitude as score
        metrics.append(variant.upvote_ratio * 100.0)
    if variant.engagement_rate is not None:
        metrics.append(float(variant.engagement_rate))
    return metrics


def _collect_historical_metrics(db: Session, subreddit: str, exclude_test_id: int) -> dict[str, list[float]]:
    """
    Gather metric vectors from previously concluded variants in the same
    subreddit.  Keyed by variant strategy so we can enrich the sample.
    """
    concluded = (
        db.query(ABVariant)
        .join(ABTest)
        .filter(
            ABTest.subreddit == subreddit,
            ABTest.id != exclude_test_id,
            ABVariant.status == "concluded",
            ABVariant.score.isnot(None),
        )
        .all()
    )
    pools: dict[str, list[float]] = {}
    for v in concluded:
        key = v.title_strategy or "unknown"
        pools.setdefault(key, []).extend(_build_metric_vector(v))
    return pools


MIN_SAMPLE_SIZE = int(os.getenv("AB_MIN_SAMPLE_SIZE", "4"))


def analyze_test(db: Session, test: ABTest) -> dict:
    """
    Compare variant performance using a two-sample statistical test.

    Strategy:
    1. Build a metric vector per variant (score, comments, upvote_ratio,
       engagement_rate).
    2. Enrich each vector with historical data from the same subreddit /
       strategy when available.
    3. If both samples have >= MIN_SAMPLE_SIZE observations, run a
       Mann-Whitney U test (non-parametric, robust for small / non-normal
       samples).  Fall back to Welch's t-test when samples are large enough
       (>= 20 each).
    4. Conclude the test when p < significance_threshold.
    """
    variants = [v for v in test.variants if v.status == "live" and v.score is not None]
    if len(variants) < 2:
        return {"status": "insufficient_data", "message": "Need at least 2 live variants with data."}

    result: dict = {
        "test_id": test.id,
        "variants": [],
        "winner": None,
        "p_value": None,
        "significant": False,
    }

    for v in variants:
        result["variants"].append({
            "label": v.variant_label,
            "title": v.title,
            "score": v.score,
            "upvote_ratio": v.upvote_ratio,
            "num_comments": v.num_comments,
            "engagement_rate": v.engagement_rate,
            "strategy": v.title_strategy,
        })

    significance_threshold = float(os.getenv("AB_SIGNIFICANCE_THRESHOLD", "0.05"))

    if len(variants) == 2:
        a, b = variants[0], variants[1]

        # --- Build sample vectors ------------------------------------------------
        sample_a = _build_metric_vector(a)
        sample_b = _build_metric_vector(b)

        # Enrich with historical concluded-variant data from same subreddit
        history = _collect_historical_metrics(db, test.subreddit, test.id)
        strategy_a = a.title_strategy or "unknown"
        strategy_b = b.title_strategy or "unknown"
        if strategy_a in history:
            sample_a.extend(history[strategy_a])
        if strategy_b in history:
            sample_b.extend(history[strategy_b])

        # --- Determine a winner by composite engagement -------------------------
        a_metric = a.engagement_rate if a.engagement_rate is not None else (a.score or 0)
        b_metric = b.engagement_rate if b.engagement_rate is not None else (b.score or 0)
        winner = a if a_metric >= b_metric else b
        loser = b if winner is a else a
        denom = max(min(a_metric, b_metric), 1)
        improvement = abs(a_metric - b_metric) / denom * 100

        result["winner"] = winner.variant_label
        result["improvement_pct"] = round(improvement, 1)
        result["better_strategy"] = winner.title_strategy
        result["sample_sizes"] = {"a": len(sample_a), "b": len(sample_b)}

        # --- Statistical test ---------------------------------------------------
        enough_data = len(sample_a) >= MIN_SAMPLE_SIZE and len(sample_b) >= MIN_SAMPLE_SIZE

        if enough_data:
            # Mann-Whitney U: non-parametric, works well for small/skewed samples
            try:
                u_stat, p_value = stats.mannwhitneyu(
                    sample_a, sample_b, alternative="two-sided",
                )
            except ValueError:
                # All-identical values or degenerate input
                p_value = 1.0

            # For larger samples, also run Welch's t-test and take the
            # more conservative (higher) p-value
            if len(sample_a) >= 20 and len(sample_b) >= 20:
                _, t_p = stats.ttest_ind(sample_a, sample_b, equal_var=False)
                p_value = max(p_value, t_p)

            result["p_value"] = round(p_value, 6)

            if p_value < significance_threshold:
                result["significant"] = True
                _conclude_test(db, test, winner.id, p_value=p_value)
        else:
            result["p_value"] = None
            result["note"] = (
                f"Insufficient sample size (need {MIN_SAMPLE_SIZE} per variant, "
                f"have {len(sample_a)} / {len(sample_b)}). "
                "Collect more data or run more A/B tests in this subreddit."
            )

    result["status"] = "significant" if result["significant"] else "inconclusive"
    return result


def _conclude_test(db: Session, test: ABTest, winner_variant_id: int, p_value: float) -> None:
    test.is_active = False  # type: ignore[assignment]
    test.concluded_at = datetime.now(UTC)  # type: ignore[assignment]
    test.winner_variant_id = winner_variant_id  # type: ignore[assignment]
    test.significance_achieved = True  # type: ignore[assignment]
    test.p_value = p_value  # type: ignore[assignment]
    for v in test.variants:
        v.status = "concluded"  # type: ignore[assignment]
    db.commit()
    logger.info(f"[A/B] Test #{test.id} concluded. Winner variant #{winner_variant_id}.")
