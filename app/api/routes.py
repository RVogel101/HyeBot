"""
All API routes — dashboard stats, scraping controls, post idea CRUD,
A/B test management, Reddit data collection, and engagement analysis.
"""
import logging
import os
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.source import Article, Source
from app.models.post import PostIdea, PostStatus
from app.models.ab_test import ABTest, ABVariant, PostPerformance
from app.models.reddit_data import RedditPost, EngagementPattern
from app.scrapers.scraping_service import run_all_scrapes, run_news_scrape, run_history_scrape
from app.analysis.reddit_collector import collect_reddit_data
from app.analysis.engagement_analyzer import analyze_engagement_patterns, get_recommendations
from app.analysis.post_generator import generate_post_ideas
from app.ab_testing.ab_framework import (
    create_ab_test, post_idea_to_reddit, post_variant_to_reddit,
    refresh_variant_metrics, refresh_post_performance, analyze_test,
)

router = APIRouter()
logger = logging.getLogger(__name__)

TARGET_SUBREDDIT = os.getenv("TARGET_SUBREDDIT", "armenia")


# ─── Pydantic schemas ──────────────────────────────────────────────────────────

class PostIdeaUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    notes: Optional[str] = None


class PostIdeaApprove(BaseModel):
    post_immediately: bool = False
    create_ab_test: bool = True
    num_ab_variants: int = 2


class PostIdeaReject(BaseModel):
    reason: Optional[str] = None


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """High-level dashboard statistics."""
    return {
        "sources": db.query(Source).count(),
        "articles_scraped": db.query(Article).count(),
        "post_ideas": {
            "total": db.query(PostIdea).count(),
            "pending": db.query(PostIdea).filter_by(status=PostStatus.pending).count(),
            "approved": db.query(PostIdea).filter_by(status=PostStatus.approved).count(),
            "posted": db.query(PostIdea).filter_by(status=PostStatus.posted).count(),
            "rejected": db.query(PostIdea).filter_by(status=PostStatus.rejected).count(),
        },
        "ab_tests": {
            "total": db.query(ABTest).count(),
            "active": db.query(ABTest).filter_by(is_active=True).count(),
            "concluded": db.query(ABTest).filter_by(is_active=False).count(),
        },
        "reddit_posts_analyzed": db.query(RedditPost).count(),
        "engagement_patterns": db.query(EngagementPattern).count(),
    }


# ─── Sources ──────────────────────────────────────────────────────────────────

@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    sources = db.query(Source).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "category": s.category,
            "is_active": s.is_active,
            "article_count": s.article_count,
            # avoid truthiness on Column[datetime]
            "last_scraped_at": s.last_scraped_at.isoformat() if s.last_scraped_at is not None else None,
        }
        for s in sources
    ]


# ─── Scraping controls ────────────────────────────────────────────────────────

@router.post("/scrape/all")
def trigger_full_scrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Start a full scrape (news + history) in the background."""
    background_tasks.add_task(_bg_scrape_all, db)
    return {"status": "scrape started", "type": "all"}


@router.post("/scrape/news")
def trigger_news_scrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(run_news_scrape, db)
    return {"status": "scrape started", "type": "news"}


@router.post("/scrape/history")
def trigger_history_scrape(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(run_history_scrape, db)
    return {"status": "scrape started", "type": "history"}


def _bg_scrape_all(db: Session):
    run_all_scrapes(db)


# ─── Articles ─────────────────────────────────────────────────────────────────

@router.get("/articles")
def list_articles(
    skip: int = 0,
    limit: int = 50,
    category: Optional[str] = None,
    processed: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Article)
    if category:
        q = q.filter_by(category=category)
    if processed is not None:
        q = q.filter_by(is_processed=processed)
    total = q.count()
    articles = q.order_by(Article.scraped_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source_id": a.source_id,
                "category": a.category,
                "summary": a.summary,
                # avoid truthiness on Column[datetime]
                "published_at": a.published_at.isoformat() if a.published_at is not None else None,
                "scraped_at": a.scraped_at.isoformat() if a.scraped_at is not None else None,
                "is_processed": a.is_processed,
            }
            for a in articles
        ],
    }


# ─── Post ideas ───────────────────────────────────────────────────────────────

@router.get("/post-ideas")
def list_post_ideas(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(PostIdea)
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    ideas = q.order_by(PostIdea.generated_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [_post_idea_dict(i) for i in ideas],
    }


@router.get("/post-ideas/{idea_id}")
def get_post_idea(idea_id: int, db: Session = Depends(get_db)):
    idea = db.query(PostIdea).filter_by(id=idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Post idea not found")
    return _post_idea_dict(idea)


@router.patch("/post-ideas/{idea_id}")
def update_post_idea(idea_id: int, body: PostIdeaUpdate, db: Session = Depends(get_db)):
    idea = db.query(PostIdea).filter_by(id=idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Post idea not found")
    if body.title is not None:
        if len(body.title) > 300:
            raise HTTPException(status_code=422, detail="Title exceeds 300 character Reddit limit")
        idea.title = body.title  # type: ignore[assignment]
    if body.body is not None:
        idea.body = body.body  # type: ignore[assignment]
    if body.notes is not None:
        idea.notes = body.notes  # type: ignore[assignment]
    db.commit()
    return _post_idea_dict(idea)


@router.post("/post-ideas/{idea_id}/approve")
def approve_post_idea(
    idea_id: int,
    body: PostIdeaApprove,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Approve a post idea. Optionally post immediately or create an A/B test.
    """
    idea = db.query(PostIdea).filter_by(id=idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Post idea not found")
    if idea.status not in (PostStatus.pending, PostStatus.rejected):
        raise HTTPException(status_code=400, detail=f"Idea is already '{idea.status}'")

    idea.status = PostStatus.approved  # type: ignore[assignment]
    idea.reviewed_at = datetime.now(UTC)  # type: ignore[assignment]
    db.commit()

    response = {"status": "approved", "idea_id": idea_id}

    if body.create_ab_test:
        test = create_ab_test(db, idea, num_variants=body.num_ab_variants)
        response["ab_test_id"] = test.id
        response["message"] = f"A/B test #{test.id} created with {body.num_ab_variants} variants."
    elif body.post_immediately:
        background_tasks.add_task(post_idea_to_reddit, db, idea)
        response["message"] = "Post submitted to Reddit in background."

    return response


@router.post("/post-ideas/{idea_id}/reject")
def reject_post_idea(idea_id: int, body: PostIdeaReject, db: Session = Depends(get_db)):
    idea = db.query(PostIdea).filter_by(id=idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Post idea not found")
    idea.status = PostStatus.rejected  # type: ignore[assignment]
    idea.reviewed_at = datetime.now(UTC)  # type: ignore[assignment]
    if body.reason:
        idea.notes = body.reason  # type: ignore[assignment]
    db.commit()
    return {"status": "rejected", "idea_id": idea_id}


@router.post("/generate-ideas")
def generate_ideas(
    max_ideas: int = 20,
    subreddit: str = TARGET_SUBREDDIT,
    db: Session = Depends(get_db),
):
    """Trigger post idea generation from unprocessed articles."""
    ideas = generate_post_ideas(db, subreddit=subreddit, max_ideas=max_ideas)
    return {
        "generated": len(ideas),
        "ideas": [_post_idea_dict(i) for i in ideas],
    }


def _post_idea_dict(idea: PostIdea) -> dict:
    return {
        "id": idea.id,
        "title": idea.title,
        "body": idea.body,
        "post_type": idea.post_type,
        "target_subreddit": idea.target_subreddit,
        "source_url": idea.source_url,
        "source_category": idea.source_category,
        "status": idea.status,
        "generation_method": idea.generation_method,
        "predicted_engagement_score": idea.predicted_engagement_score,
        "notes": idea.notes,
        # avoid truthiness on Column[datetime]
        "generated_at": idea.generated_at.isoformat() if idea.generated_at is not None else None,
        "reviewed_at": idea.reviewed_at.isoformat() if idea.reviewed_at is not None else None,
        "posted_at": idea.posted_at.isoformat() if idea.posted_at is not None else None,
        "reddit_post_id": idea.reddit_post_id,
        "article_id": idea.article_id,
    }


# ─── A/B tests ────────────────────────────────────────────────────────────────

@router.get("/ab-tests")
def list_ab_tests(db: Session = Depends(get_db)):
    tests = db.query(ABTest).order_by(ABTest.created_at.desc()).all()
    return [_ab_test_dict(t) for t in tests]


@router.get("/ab-tests/{test_id}")
def get_ab_test(test_id: int, db: Session = Depends(get_db)):
    test = db.query(ABTest).filter_by(id=test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    return _ab_test_dict(test, include_variants=True)


@router.post("/ab-tests/{test_id}/post-variants")
def post_ab_variants(
    test_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Post all draft variants in this A/B test to Reddit (sequentially with delays)."""
    test = db.query(ABTest).filter_by(id=test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    draft_variants = [v for v in test.variants if v.status == "draft"]
    if not draft_variants:
        return {"message": "No draft variants to post."}

    # Post variants sequentially in a single background task with delays
    # to comply with Reddit rate limits and spam prevention
    def _post_variants_sequentially():
        import time
        for i, variant in enumerate(draft_variants):
            post_variant_to_reddit(db, variant)
            # Wait between variant posts (skip delay after last one)
            if i < len(draft_variants) - 1:
                delay = int(os.getenv("POSTING_COOLDOWN_SECONDS", "600"))
                logger.info(f"[A/B] Waiting {delay}s before posting next variant…")
                time.sleep(delay)

    background_tasks.add_task(_post_variants_sequentially)
    return {"message": f"Posting {len(draft_variants)} variants sequentially in background (with cooldown delays)."}


@router.post("/ab-tests/{test_id}/refresh-metrics")
def refresh_ab_metrics(test_id: int, db: Session = Depends(get_db)):
    test = db.query(ABTest).filter_by(id=test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    refresh_variant_metrics(db, test)
    return {"status": "metrics refreshed", "test_id": test_id}


@router.post("/ab-tests/{test_id}/analyze")
def analyze_ab_test(test_id: int, db: Session = Depends(get_db)):
    test = db.query(ABTest).filter_by(id=test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found")
    return analyze_test(db, test)


def _ab_test_dict(test: ABTest, include_variants: bool = False) -> dict:
    d = {
        "id": test.id,
        "name": test.name,
        "subreddit": test.subreddit,
        "is_active": test.is_active,
        "significance_achieved": test.significance_achieved,
        "p_value": test.p_value,
        "winner_variant_id": test.winner_variant_id,
        # avoid truthiness on Column[datetime]
        "created_at": test.created_at.isoformat() if test.created_at is not None else None,
        "concluded_at": test.concluded_at.isoformat() if test.concluded_at is not None else None,
    }
    if include_variants:
        d["variants"] = [
            {
                "id": v.id,
                "label": v.variant_label,
                "title": v.title,
                "title_strategy": v.title_strategy,
                "status": v.status,
                "reddit_post_id": v.reddit_post_id,
                "score": v.score,
                "upvote_ratio": v.upvote_ratio,
                "num_comments": v.num_comments,
                "engagement_rate": v.engagement_rate,
                "posted_at": v.posted_at.isoformat() if v.posted_at else None,
            }
            for v in test.variants
        ]
    return d


# ─── Reddit data & analysis ───────────────────────────────────────────────────

@router.post("/reddit/collect")
def trigger_reddit_collect(
    background_tasks: BackgroundTasks,
    subreddits: Optional[str] = None,
    posts_per_sub: int = 100,
    db: Session = Depends(get_db),
):
    """Collect Reddit engagement data from analysis subreddits."""
    sub_list = [s.strip() for s in subreddits.split(",")] if subreddits else None
    background_tasks.add_task(collect_reddit_data, db, sub_list, posts_per_sub)
    return {"status": "collection started", "subreddits": sub_list or "from config"}


@router.post("/reddit/analyze")
def trigger_analysis(
    subreddit: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Run engagement pattern analysis on collected Reddit data."""
    result = analyze_engagement_patterns(db, subreddit=subreddit)
    return result


@router.get("/reddit/recommendations")
def get_subreddit_recommendations(
    subreddit: str = TARGET_SUBREDDIT,
    db: Session = Depends(get_db),
):
    return get_recommendations(db, subreddit=subreddit)


@router.get("/reddit/posts")
def list_reddit_posts(
    subreddit: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(RedditPost)
    if subreddit:
        q = q.filter_by(subreddit=subreddit)
    total = q.count()
    posts = q.order_by(RedditPost.score.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": p.id,
                "reddit_id": p.reddit_post_id,
                "subreddit": p.subreddit,
                "title": p.title,
                "score": p.score,
                "upvote_ratio": p.upvote_ratio,
                "num_comments": p.num_comments,
                "author": p.author,
                "permalink": f"https://reddit.com/r/{p.subreddit}/comments/{p.reddit_post_id}" if p.reddit_post_id is not None else None,
                "post_type": p.post_type,
                "has_question": p.has_question,
                "has_numbers": p.has_numbers,
                "title_word_count": p.title_word_count,
                "sentiment_score": p.sentiment_score,
                # avoid truthiness on Column[datetime]
                "created_utc": p.created_utc.isoformat() if p.created_utc is not None else None,
            }
            for p in posts
        ],
    }


@router.get("/reddit/patterns")
def list_engagement_patterns(
    subreddit: Optional[str] = None,
    pattern_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(EngagementPattern)
    if subreddit:
        q = q.filter_by(subreddit=subreddit)
    if pattern_type:
        q = q.filter_by(pattern_type=pattern_type)
    patterns = q.order_by(EngagementPattern.avg_score.desc()).all()
    return [
        {
            "subreddit": p.subreddit,
            "type": p.pattern_type,
            "value": p.pattern_value,
            "avg_score": p.avg_score,
            "sample_count": p.sample_count,
        }
        for p in patterns
    ]
