"""
Scrapers for Armenian news media sources.
Covers: Armenpress, Asbarez, Armenian Weekly, Azatutyun, Hetq,
        Panorama.am, EVN Report, OC Media, Civilnet.
"""
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser

from app.scrapers.base_scraper import BaseScraper, ScrapedArticle

logger = logging.getLogger(__name__)


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse an RFC-2822 / RSS date string into a timezone-aware datetime."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        try:
            return datetime(*feedparser._parse_date(date_str)[:6], tzinfo=timezone.utc)
        except Exception:
            return None


class RSSNewsScraper(BaseScraper):
    """
    Generic RSS-feed scraper.  All Armenian news sources that expose an RSS
    feed use this class; source-specific behaviour is handled by subclasses.
    """

    def __init__(self, name: str, base_url: str, rss_url: str, category: str = "news"):
        super().__init__(name, base_url)
        self.rss_url = rss_url
        self.category = category

    def scrape(self) -> list[ScrapedArticle]:
        logger.info(f"[{self.name}] Fetching RSS feed: {self.rss_url}")
        try:
            feed = feedparser.parse(self.rss_url)
        except Exception as exc:
            logger.error(f"[{self.name}] RSS parse error: {exc}")
            return []

        articles: list[ScrapedArticle] = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            if not title or not url:
                continue

            summary = self.clean_text(
                entry.get("summary", entry.get("description", ""))
            )
            # Strip HTML tags from summary
            from bs4 import BeautifulSoup
            summary = BeautifulSoup(summary, "lxml").get_text(separator=" ")
            summary = self.clean_text(summary)

            published_at = _parse_rss_date(
                entry.get("published", entry.get("updated", ""))
            )

            tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

            articles.append(
                ScrapedArticle(
                    title=title,
                    url=url,
                    content="",  # Full content fetched on demand
                    summary=summary[:1000],
                    published_at=published_at,
                    category=self.category,
                    tags=tags,
                )
            )

        logger.info(f"[{self.name}] Collected {len(articles)} articles from RSS.")
        return articles

    def fetch_full_content(self, url: str) -> str:
        """Fetch and extract the main article text from the article page."""
        resp = self.fetch(url)
        if not resp:
            return ""
        soup = self.parse_html(resp.text)
        # Remove boilerplate elements
        for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                                   "aside", "form", "iframe", "noscript"]):
            tag.decompose()
        # Try common article content containers
        for selector in ["article", ".article-body", ".entry-content",
                         ".post-content", ".content", "main"]:
            container = soup.select_one(selector)
            if container:
                return self.clean_text(container.get_text(separator=" "))
        return self.clean_text(soup.body.get_text(separator=" ") if soup.body else "")


# ---------------------------------------------------------------------------
# Named scrapers (thin wrappers for discoverability / future customisation)
# ---------------------------------------------------------------------------

class ArmenPressScraper(RSSNewsScraper):
    SOURCE_NAME = "Armenpress"
    BASE_URL = "https://armenpress.am/eng/news/"
    RSS_URL = "https://armenpress.am/eng/rss/news/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class AsbarezScraper(RSSNewsScraper):
    SOURCE_NAME = "Asbarez"
    BASE_URL = "https://asbarez.com"
    RSS_URL = "https://asbarez.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class ArmenianWeeklyScraper(RSSNewsScraper):
    SOURCE_NAME = "Armenian Weekly"
    BASE_URL = "https://armenianweekly.com"
    RSS_URL = "https://armenianweekly.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class AzatutyunScraper(RSSNewsScraper):
    SOURCE_NAME = "Azatutyun (RFE/RL Armenia)"
    BASE_URL = "https://www.azatutyun.am"
    RSS_URL = "https://www.azatutyun.am/api/zijrreypui"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class HetqScraper(RSSNewsScraper):
    SOURCE_NAME = "Hetq"
    BASE_URL = "https://hetq.am/en/news"
    RSS_URL = "https://hetq.am/en/rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "investigative")


class PanoramaScraper(RSSNewsScraper):
    SOURCE_NAME = "Panorama.am"
    BASE_URL = "https://www.panorama.am/en/news/"
    RSS_URL = "https://www.panorama.am/en/rss/news.xml"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class EVNReportScraper(RSSNewsScraper):
    SOURCE_NAME = "EVN Report"
    BASE_URL = "https://evnreport.com"
    RSS_URL = "https://evnreport.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "analysis")


class OCMediaScraper(RSSNewsScraper):
    SOURCE_NAME = "OC Media"
    BASE_URL = "https://oc-media.org"
    RSS_URL = "https://oc-media.org/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class CivilnetScraper(RSSNewsScraper):
    SOURCE_NAME = "Civilnet"
    BASE_URL = "https://www.civilnet.am/en/"
    RSS_URL = "https://www.civilnet.am/en/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "culture")


class ArmenianMirrorSpectatorScraper(RSSNewsScraper):
    SOURCE_NAME = "Armenian Mirror-Spectator"
    BASE_URL = "https://mirrorspectator.com"
    RSS_URL = "https://mirrorspectator.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class MassisPostScraper(RSSNewsScraper):
    SOURCE_NAME = "Massis Post"
    BASE_URL = "https://www.massispost.com"
    RSS_URL = "https://www.massispost.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class NewsAmScraper(RSSNewsScraper):
    SOURCE_NAME = "News.am"
    BASE_URL = "https://news.am/eng"
    RSS_URL = "https://news.am/eng/rss/all.rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


class LragirScraper(RSSNewsScraper):
    SOURCE_NAME = "Lragir.am"
    BASE_URL = "https://www.lragir.am/en"
    RSS_URL = "https://www.lragir.am/en/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "analysis")


class MediamaxScraper(RSSNewsScraper):
    SOURCE_NAME = "Mediamax"
    BASE_URL = "https://mediamax.am/en"
    RSS_URL = "https://mediamax.am/en/rss/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "news")


# ---------------------------------------------------------------------------
# Registry — used by the scraping service to iterate all news sources
# ---------------------------------------------------------------------------

ALL_NEWS_SCRAPERS = [
    ArmenPressScraper,
    AsbarezScraper,
    ArmenianWeeklyScraper,
    AzatutyunScraper,
    HetqScraper,
    PanoramaScraper,
    EVNReportScraper,
    OCMediaScraper,
    CivilnetScraper,
    ArmenianMirrorSpectatorScraper,
    MassisPostScraper,
    NewsAmScraper,
    LragirScraper,
    MediamaxScraper,
]
