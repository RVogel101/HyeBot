"""
Scrapers for Armenian news media sources and international outlets.
Covers: Armenpress, Asbarez, Armenian Weekly, Azatutyun, Hetq,
        Panorama.am, EVN Report, OC Media, Civilnet,
        Massis Post, Armenian Mirror-Spectator, Horizon Weekly, Agos.
International (keyword-filtered):
        Google News Armenia, Al Jazeera, Al-Monitor, BBC World,
        France 24, Deutsche Welle, Euronews.
"""
import logging
import re
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
            # feedparser may return lists for some fields; coerce to str first
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("link", "")).strip()
            if not title or not url:
                continue

            summary = str(entry.get("summary", entry.get("description", "")))
            summary = self.clean_text(summary)
            # Strip HTML tags from summary
            from bs4 import BeautifulSoup
            summary = BeautifulSoup(summary, "lxml").get_text(separator=" ")
            summary = self.clean_text(summary)

            published_at = _parse_rss_date(
                str(entry.get("published", entry.get("updated", "")) or "")
            )

            # entry.get may return None; ensure we have a list before iterating
            raw_tags = entry.get("tags") or []
            tags = [str(t.get("term", "")) for t in raw_tags if t and t.get("term")]

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
# Armenian keyword list — used to filter international feeds
# ---------------------------------------------------------------------------

ARMENIAN_KEYWORDS: list[str] = [
    # Country / people
    r"\barmenia\b", r"\barmenian[s]?\b", r"\bhay(?:astan)?\b",
    # Cities & regions
    r"\byerevan\b", r"\bgyumri\b", r"\bvanadzor\b",
    # Artsakh / Karabakh
    r"\bartsakh\b", r"\bkarabakh\b", r"\bnagorno[- ]?karabakh\b",
    # Geopolitical actors & events
    r"\bpashinyan\b", r"\bkocharyan\b", r"\bsargsyan\b",
    r"\barmenian[- ]?genocide\b", r"\b1915\b.*(?:ottoman|turkey|armenian)",
    # Diaspora & church
    r"\barmenian[- ]?diaspora\b", r"\barmenian[- ]?apostolic\b",
    r"\bechmiadz[iy]n\b", r"\bcatholic[ao]s\b",
    # South Caucasus context
    r"\bsouth[- ]?caucasus\b", r"\bcaucasus\b.*armenian",
    # Armenian Jerusalem
    r"\barmenian[- ]?quarter\b", r"\barmenian[- ]?patriarch",
    r"\bjerusalem\b.*armenian",
    r"\bcows[- ]?garden\b",
]

_ARMENIAN_PATTERN: re.Pattern[str] = re.compile(
    "|".join(ARMENIAN_KEYWORDS), re.IGNORECASE
)


def _matches_armenian_keywords(text: str) -> bool:
    """Return True if *text* contains at least one Armenian-related keyword."""
    return bool(_ARMENIAN_PATTERN.search(text))


class KeywordFilteredRSSScraper(RSSNewsScraper):
    """
    RSS scraper that **only** keeps articles matching Armenian-related
    keywords in their title or summary.  Used for large international feeds
    (BBC, Al Jazeera, France 24 …) where only a fraction of output is
    relevant to the Armenian beat.
    """

    def scrape(self) -> list[ScrapedArticle]:
        all_articles = super().scrape()
        filtered = [
            a for a in all_articles
            if _matches_armenian_keywords(a.title)
            or _matches_armenian_keywords(a.summary)
        ]
        logger.info(
            f"[{self.name}] Keyword filter: {len(filtered)}/{len(all_articles)} "
            "articles matched Armenian keywords."
        )
        return filtered


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


# ---------------------------------------------------------------------------
# Diaspora sources
# ---------------------------------------------------------------------------

class MassisPostScraper(RSSNewsScraper):
    """Massis Post — Los Angeles-based Armenian diaspora news."""
    SOURCE_NAME = "Massis Post"
    BASE_URL = "https://massispost.com"
    RSS_URL = "https://massispost.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "diaspora")


class MirrorSpectatorScraper(RSSNewsScraper):
    """Armenian Mirror-Spectator — Boston/Watertown, oldest Armenian weekly in the US."""
    SOURCE_NAME = "Armenian Mirror-Spectator"
    BASE_URL = "https://mirrorspectator.com"
    RSS_URL = "https://mirrorspectator.com/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "diaspora")


class HorizonWeeklyScraper(RSSNewsScraper):
    """Horizon Weekly — Canada's ARF Armenian weekly publication."""
    SOURCE_NAME = "Horizon Weekly"
    BASE_URL = "https://horizonweekly.ca"
    RSS_URL = "https://horizonweekly.ca/feed/"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "diaspora")


class AgosScraper(RSSNewsScraper):
    """Agos — Istanbul Armenian bilingual newspaper (English section)."""
    SOURCE_NAME = "Agos"
    BASE_URL = "https://www.agos.com.tr/en"
    RSS_URL = "https://www.agos.com.tr/en/rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "diaspora")


# ---------------------------------------------------------------------------
# International / regional keyword-filtered sources
# ---------------------------------------------------------------------------

class GoogleNewsArmenianScraper(RSSNewsScraper):
    """
    Google News pre-filtered RSS for 'Armenia OR Armenian'.
    Already keyword-filtered by Google, so uses plain RSSNewsScraper.
    Aggregates coverage from NYT, Jerusalem Post, Reuters, CFR, etc.
    """
    SOURCE_NAME = "Google News – Armenia"
    BASE_URL = "https://news.google.com"
    RSS_URL = (
        "https://news.google.com/rss/search?"
        "q=Armenia+OR+Armenian+OR+Artsakh+OR+Karabakh&hl=en-US&gl=US&ceid=US:en"
    )

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class AlJazeeraScraper(KeywordFilteredRSSScraper):
    """Al Jazeera English — Middle East focused, keyword-filtered for Armenian content."""
    SOURCE_NAME = "Al Jazeera (Armenian)"
    BASE_URL = "https://www.aljazeera.com"
    RSS_URL = "https://www.aljazeera.com/xml/rss/all.xml"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class AlMonitorScraper(KeywordFilteredRSSScraper):
    """Al-Monitor — Middle East policy news, keyword-filtered for Armenian content."""
    SOURCE_NAME = "Al-Monitor (Armenian)"
    BASE_URL = "https://www.al-monitor.com"
    RSS_URL = "https://www.al-monitor.com/rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class BBCWorldScraper(KeywordFilteredRSSScraper):
    """BBC World News — keyword-filtered for Armenian content."""
    SOURCE_NAME = "BBC World (Armenian)"
    BASE_URL = "https://www.bbc.co.uk/news/world"
    RSS_URL = "https://feeds.bbci.co.uk/news/world/rss.xml"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class France24Scraper(KeywordFilteredRSSScraper):
    """France 24 English — EU/international news, keyword-filtered for Armenian content."""
    SOURCE_NAME = "France 24 (Armenian)"
    BASE_URL = "https://www.france24.com/en/"
    RSS_URL = "https://www.france24.com/en/rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class DWWorldScraper(KeywordFilteredRSSScraper):
    """Deutsche Welle — German international broadcaster, keyword-filtered for Armenian content."""
    SOURCE_NAME = "Deutsche Welle (Armenian)"
    BASE_URL = "https://www.dw.com/en/"
    RSS_URL = "https://rss.dw.com/xml/rss-en-world"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


class EuronewsScraper(KeywordFilteredRSSScraper):
    """Euronews — pan-European news, keyword-filtered for Armenian content."""
    SOURCE_NAME = "Euronews (Armenian)"
    BASE_URL = "https://www.euronews.com"
    RSS_URL = "https://www.euronews.com/rss"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL, self.RSS_URL, "international")


# ---------------------------------------------------------------------------
# Registry — used by the scraping service to iterate all news sources
# ---------------------------------------------------------------------------

ALL_NEWS_SCRAPERS = [
    # Armenia-based
    ArmenPressScraper,
    AsbarezScraper,
    ArmenianWeeklyScraper,
    AzatutyunScraper,
    HetqScraper,
    PanoramaScraper,
    EVNReportScraper,
    OCMediaScraper,
    CivilnetScraper,
    # Diaspora
    MassisPostScraper,
    MirrorSpectatorScraper,
    HorizonWeeklyScraper,
    AgosScraper,
    # International / regional (keyword-filtered)
    GoogleNewsArmenianScraper,
    AlJazeeraScraper,
    AlMonitorScraper,
    BBCWorldScraper,
    France24Scraper,
    DWWorldScraper,
    EuronewsScraper,
]
