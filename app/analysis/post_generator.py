"""
Post idea generator — takes scraped articles and produces Reddit post ideas
modelled after high-engagement patterns discovered by the analyzer.
"""
import json
import logging
import os
import re
import random
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session

from app.models.source import Article
from app.models.post import PostIdea
from app.models.reddit_data import EngagementPattern

logger = logging.getLogger(__name__)

TARGET_SUBREDDIT = os.getenv("TARGET_SUBREDDIT", "armenia")

# ─── Title templates keyed by structure type ───────────────────────────────────
# Placeholders: {topic}, {detail}, {number}, {keyword}
TEMPLATES: dict[str, list[str]] = {
    "question": [
        "What do you think about {topic}?",
        "Did you know that {detail}? Thoughts?",
        "Is {topic} the most under-reported story of the year?",
        "Why is {topic} not getting more attention?",
        "How should the Armenian community respond to {detail}?",
    ],
    "topic_colon_detail": [
        "{topic}: {detail}",
        "Breaking — {topic}: {detail}",
        "{topic} — what this means for Armenia",
        "{topic}: A deep dive into {detail}",
    ],
    "starts_with_number": [
        "{number} things you should know about {topic}",
        "{number} years since {detail} — looking back",
        "{number} key takeaways from {topic}",
    ],
    "short_punchy": [
        "{topic} — important",
        "{topic}: big news",
        "{topic}",
    ],
    "long_descriptive": [
        "In-depth: {topic} and its implications for {detail}",
        "A comprehensive look at {topic}: understanding {detail} in context",
        "Everything you need to know about {topic} as {detail} unfolds",
    ],
    "breaking_news": [
        "Breaking: {detail}",
        "Just in: {topic} — {detail}",
    ],
    "standard": [
        "{topic} — {detail}",
        "{detail} ({topic})",
        "Interesting development: {topic}",
    ],
}

HISTORY_TEMPLATES = [
    "On this day in Armenian history: {detail}",
    "TIL: {detail} — a piece of Armenian history",
    "History corner: {topic} — {detail}",
    "{number} fascinating facts about {topic} in Armenian history",
    "The story of {topic}: {detail}",
    "Remembering {topic}: {detail}",
]

INVESTIGATION_TEMPLATES = [
    "Investigative report: {topic} — {detail}",
    "{detail} — an investigative look at {topic}",
    "Inside story: {topic}",
]

ANALYSIS_TEMPLATES = [
    "Analysis: {topic} — what it means for Armenia",
    "Opinion: {detail} ({topic})",
    "{topic}: an analytical perspective on {detail}",
]


def _choose_template(category: str, structure: Optional[str] = None) -> str:
    """Pick an appropriate title template based on content category."""
    if category == "history":
        return random.choice(HISTORY_TEMPLATES)
    if category == "investigative":
        return random.choice(INVESTIGATION_TEMPLATES)
    if category == "analysis":
        return random.choice(ANALYSIS_TEMPLATES)
    pool = TEMPLATES.get(structure or "standard", TEMPLATES["standard"])
    return random.choice(pool)


def _extract_topic(article: Article) -> tuple[str, str]:
    """
    Extract a short topic phrase and a detail phrase from an article.
    Returns (topic, detail).
    """
    # ensure we work with a plain string (SQLAlchemy attributes are typed as Any)
    title: str = str(article.title or "")
    # Remove site name suffixes like " | Armenpress" or " - Armenian Weekly"
    title = re.sub(
        r"\s*[\|\-–]\s*(armenpress|armenian weekly|asbarez|hetq|panorama|azatutyun|evn|oc media|civilnet|wikipedia).*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = title.strip()

    # Use the scraped summary for detail
    summary: str = str(article.summary or "")
    detail = summary[:120].strip() if summary else title

    # Truncate title to a clean topic phrase
    topic = title[:100].strip()
    return topic, detail


def _get_best_structure(db: Session, subreddit: str) -> str:
    """Look up the best-performing title structure for this subreddit."""
    best = (
        db.query(EngagementPattern)
        .filter_by(subreddit=subreddit, pattern_type="title_structure")
        .order_by(EngagementPattern.avg_score.desc())
        .first()
    )
    if best:
        # SQLAlchemy column access returns a Column object; coerce to plain str
        return str(best.pattern_value)
    return "standard"


def _get_top_keywords(db: Session, subreddit: str) -> list[str]:
    """Fetch the top 10 high-engagement keywords for this subreddit."""
    kws = (
        db.query(EngagementPattern)
        .filter_by(subreddit=subreddit, pattern_type="keyword")
        .order_by(EngagementPattern.avg_score.desc())
        .limit(10)
        .all()
    )
    # ensure each value is converted to a plain string
    return [str(k.pattern_value) for k in kws]


def _weave_keywords(title: str, keywords: list[str]) -> str:
    """
    Try to incorporate a relevant keyword from the pool into the title
    without forcing awkward phrasing.
    """
    title_lower = title.lower()
    for kw in keywords:
        if kw in title_lower:
            return title  # Already has a keyword
    # Only add if title is short enough and keyword fits naturally
    if len(title) < 180 and keywords:
        # Don't blindly append — only add if there's a reasonable spot
        pass
    return title


def _generate_body(article: Article) -> str:
    """Generate Reddit post body text for self-posts."""
    parts = []
    # coerce columns to primitive types before truthiness tests
    summary = str(article.summary or "")
    url = str(article.url or "")
    tags_field = str(article.tags or "")

    if summary:
        parts.append(summary)
    if url:
        parts.append(f"\n\nSource: {url}")
    tags: list[str] = []
    if tags_field:
        try:
            raw_tags = json.loads(tags_field)
            if isinstance(raw_tags, list):
                tags = [str(t) for t in raw_tags[:5]]
        except Exception:
            pass
    if tags:
        parts.append(f"\n\nRelated: {', '.join(tags)}")
    return "".join(parts)[:40000]


def generate_post_ideas(
    db: Session,
    subreddit: str = TARGET_SUBREDDIT,
    max_ideas: int = 20,
    categories: Optional[list[str]] = None,
) -> list[PostIdea]:
    """
    Main entry point: generate post ideas from unprocessed articles.
    Returns a list of newly created (and committed) PostIdea rows.
    """
    if categories is None:
        categories = ["news", "history", "investigative", "analysis", "culture"]

    best_structure = _get_best_structure(db, subreddit)
    top_kws = _get_top_keywords(db, subreddit)

    # Fetch unprocessed articles
    articles = (
        db.query(Article)
        .filter(Article.is_processed == False)  # noqa: E712
        .filter(Article.title.isnot(None))
        .filter(Article.category.in_(categories))
        .order_by(Article.scraped_at.desc())
        .limit(max_ideas * 2)
        .all()
    )

    ideas: list[PostIdea] = []
    seen_titles: set[str] = set()

    for article in articles:
        if len(ideas) >= max_ideas:
            break

        # coerce some columns to plain types for later use
        category = str(article.category or "news")
        url = str(article.url or "")

        topic, detail = _extract_topic(article)
        if not topic:
            continue

        template = _choose_template(category, best_structure)

        # Fill template placeholders
        raw_title = template.format(
            topic=topic[:80],
            detail=detail[:100] if detail else topic[:80],
            number=random.choice([3, 5, 7, 10]),
            keyword=top_kws[0] if top_kws else "Armenia",
        )

        # Enforce Reddit title length limit
        if len(raw_title) > 300:
            raw_title = raw_title[:297] + "..."

        raw_title = raw_title.strip()

        # Deduplicate
        norm = raw_title.lower()
        if norm in seen_titles:
            continue
        seen_titles.add(norm)

        # Determine if this should be a link post or self-post
        post_type = "link" if url else "self"

        body = "" if post_type == "link" else _generate_body(article)

        # Naive predicted engagement — use avg score of best pattern as proxy
        best_pattern = (
            db.query(EngagementPattern)
            .filter_by(subreddit=subreddit, pattern_type="title_structure",
                       pattern_value=best_structure)
            .first()
        )
        predicted_score = best_pattern.avg_score if best_pattern else None

        idea = PostIdea(
            article_id=article.id,
            title=raw_title,
            body=body,
            post_type=post_type,
            target_subreddit=subreddit,
            source_url=url,
            generation_method="template",
            predicted_engagement_score=predicted_score,
            source_category=category,
        )
        db.add(idea)

        # Mark article as processed
        article.is_processed = True  # type: ignore[assignment]

        ideas.append(idea)

    db.commit()
    logger.info(f"[Generator] Created {len(ideas)} post ideas for r/{subreddit}.")
    return ideas


def generate_ab_variants(
    db: Session,
    post_idea: PostIdea,
    num_variants: int = 2,
) -> list[dict]:
    """
    Generate multiple title variants for A/B testing from a single PostIdea.
    Returns a list of variant dicts (not yet persisted — the A/B framework does that).
    """
    subreddit = post_idea.target_subreddit
    # check for presence rather than truthiness (article_id is Column[int])
    article = (
        db.query(Article).filter_by(id=post_idea.article_id).first()
        if post_idea.article_id is not None
        else None
    )

    # coerce attributes from article for typing
    topic = str(article.title)[:80] if article else post_idea.title[:80]
    detail = str(article.summary or "")[:100] if article else ""
    category = str(article.category or "news") if article else "news"

    structures = list(TEMPLATES.keys())
    random.shuffle(structures)

    variants = []
    labels = "ABCDEFGH"
    for i in range(min(num_variants, len(structures))):
        structure = structures[i]
        template = _choose_template(category, structure)
        title = template.format(
            topic=topic,
            detail=detail or topic,
            number=random.choice([3, 5, 7, 10]),
            keyword="Armenia",
        )[:300].strip()

        variants.append({
            "label": labels[i],
            "title": title,
            "body": post_idea.body or "",
            "title_strategy": structure,
        })

    return variants
