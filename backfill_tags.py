"""
One-time migration script to backfill tags on existing articles
that have empty or missing tags.
"""
import json
import logging
import sys

from app.database import SessionLocal
from app.models.source import Article, Source
from app.scrapers.armenian_news import _auto_generate_tags

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def backfill_tags():
    db = SessionLocal()
    try:
        # Find articles with empty/missing tags
        articles = db.query(Article).all()
        updated = 0
        skipped = 0

        for article in articles:
            # Parse existing tags
            existing_tags = []
            tags_value: str = str(article.tags) if article.tags is not None else ""
            if tags_value:
                try:
                    existing_tags = json.loads(tags_value)
                except (json.JSONDecodeError, TypeError):
                    existing_tags = []

            # Skip articles that already have meaningful tags
            if existing_tags and existing_tags != ["[]"]:
                skipped += 1
                continue

            # Generate tags from title + summary + category
            title = str(article.title) if article.title is not None else ""
            summary = str(article.summary) if article.summary is not None else ""
            category = str(article.category) if article.category is not None else "news"

            new_tags = _auto_generate_tags(title, summary, category)

            if new_tags:
                article.tags = json.dumps(new_tags)  # type: ignore[assignment]
                updated += 1
                logger.info(f"  Tagged article #{article.id}: {title[:60]}... -> {new_tags}")

        db.commit()
        logger.info(f"\nBackfill complete: {updated} articles tagged, {skipped} already had tags.")
        logger.info(f"Total articles in DB: {len(articles)}")

    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    backfill_tags()