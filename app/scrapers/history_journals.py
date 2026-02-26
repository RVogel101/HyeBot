"""
Scrapers for history journals, academic sources, and Wikipedia history pages.
"""
import logging
import re
from datetime import datetime, UTC
from typing import Optional

from app.scrapers.base_scraper import BaseScraper, ScrapedArticle

logger = logging.getLogger(__name__)


class WikipediaArmenianHistoryScraper(BaseScraper):
    """
    Scrapes the 'History of Armenia' article index on Wikipedia to surface
    sub-topic articles suitable for historical Reddit posts.
    """
    SOURCE_NAME = "Wikipedia Armenian History"
    INDEX_URL = "https://en.wikipedia.org/wiki/History_of_Armenia"

    # Specific Wikipedia history pages to collect from
    HISTORY_PAGES = [
        ("History of Armenia", "https://en.wikipedia.org/wiki/History_of_Armenia"),
        ("Armenian Genocide", "https://en.wikipedia.org/wiki/Armenian_genocide"),
        ("Kingdom of Armenia (antiquity)", "https://en.wikipedia.org/wiki/Kingdom_of_Armenia_(antiquity)"),
        ("Urartu", "https://en.wikipedia.org/wiki/Urartu"),
        ("Armenian Apostolic Church", "https://en.wikipedia.org/wiki/Armenian_Apostolic_Church"),
        ("First Republic of Armenia", "https://en.wikipedia.org/wiki/First_Republic_of_Armenia"),
        ("Nagorno-Karabakh", "https://en.wikipedia.org/wiki/Nagorno-Karabakh"),
        ("Armenian diaspora", "https://en.wikipedia.org/wiki/Armenian_diaspora"),
        ("Komitas", "https://en.wikipedia.org/wiki/Komitas"),
        ("Tigran the Great", "https://en.wikipedia.org/wiki/Tigranes_the_Great"),
        ("Battle of Avarayr", "https://en.wikipedia.org/wiki/Battle_of_Avarayr"),
        ("Mesrop Mashtots", "https://en.wikipedia.org/wiki/Mesrop_Mashtots"),
        ("Mount Ararat in Armenian culture", "https://en.wikipedia.org/wiki/Mount_Ararat_in_Armenian_culture"),
        ("Treaty of Sèvres", "https://en.wikipedia.org/wiki/Treaty_of_S%C3%A8vres"),
        ("Cilician Armenia", "https://en.wikipedia.org/wiki/Armenian_Kingdom_of_Cilicia"),
    ]

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.INDEX_URL)

    def scrape(self) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        for title, url in self.HISTORY_PAGES:
            article = self._scrape_wiki_page(title, url)
            if article:
                articles.append(article)
        logger.info(f"[{self.SOURCE_NAME}] Collected {len(articles)} Wikipedia history articles.")
        return articles

    def _scrape_wiki_page(self, page_title: str, url: str) -> Optional[ScrapedArticle]:
        resp = self.fetch(url)
        if not resp:
            return None
        soup = self.parse_html(resp.text)

        # Extract lead paragraph (before first section heading)
        content_div = soup.select_one("#mw-content-text .mw-parser-output")
        if not content_div:
            return None

        paragraphs = []
        for el in content_div.children:
            if el.name == "h2":  # Stop at first section
                break
            if el.name == "p":
                text = self.clean_text(el.get_text(separator=" "))
                if len(text) > 50:
                    paragraphs.append(text)

        summary = " ".join(paragraphs[:3])
        full_paragraphs = [
            self.clean_text(p.get_text(separator=" "))
            for p in content_div.find_all("p")
            if len(p.get_text(strip=True)) > 50
        ]
        content = " ".join(full_paragraphs[:20])  # First 20 substantial paragraphs

        return ScrapedArticle(
            title=page_title,
            url=url,
            content=content[:5000],
            summary=summary[:800],
            published_at=datetime.now(UTC),
            category="history",
            tags=["history", "armenia", "wikipedia"],
        )


class HyestartScraper(BaseScraper):
    """
    Scrapes hyestart.am — an Armenian cultural and historical information portal.
    Falls back gracefully if the site structure changes.
    """
    SOURCE_NAME = "Hyestart"
    BASE_URL = "https://www.hyestart.am"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL)

    def scrape(self) -> list[ScrapedArticle]:
        resp = self.fetch(self.BASE_URL)
        if not resp:
            return []
        soup = self.parse_html(resp.text)

        articles: list[ScrapedArticle] = []
        # Collect links that seem to be article pages
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = self.clean_text(a_tag.get_text())
            if len(text) < 15 or len(text) > 300:
                continue
            url = href if href.startswith("http") else self.BASE_URL + href
            # Filter to internal pages only
            if self.BASE_URL.split("//")[1].split("/")[0] not in url:
                continue
            articles.append(
                ScrapedArticle(
                    title=text,
                    url=url,
                    summary="",
                    published_at=datetime.now(UTC),
                    category="history",
                    tags=["history", "armenia", "culture"],
                )
            )
            if len(articles) >= 20:
                break

        logger.info(f"[{self.SOURCE_NAME}] Collected {len(articles)} links.")
        return articles


class ArmenianStudiesAcademicScraper(BaseScraper):
    """
    Scrapes the CSU Fresno Armenian Studies resource pages for academic content.
    """
    SOURCE_NAME = "Armenian Studies (CSU Fresno)"
    BASE_URL = "https://armenianstudies.csufresno.edu"
    PAGES = [
        "https://armenianstudies.csufresno.edu/history/",
        "https://armenianstudies.csufresno.edu/arts_and_culture/",
    ]

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL)

    def scrape(self) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        for page_url in self.PAGES:
            category = "academic"
            if "history" in page_url:
                category = "history"
            elif "arts" in page_url:
                category = "culture"

            resp = self.fetch(page_url)
            if not resp:
                continue
            soup = self.parse_html(resp.text)

            # Remove nav / footer clutter
            for tag in soup.find_all(["nav", "footer", "script", "style"]):
                tag.decompose()

            # Extract headings + paragraph pairs as mini-articles
            for heading in soup.find_all(["h1", "h2", "h3"]):
                title = self.clean_text(heading.get_text())
                if len(title) < 10:
                    continue
                # Gather following paragraphs until next heading
                content_parts = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h1", "h2", "h3"):
                        break
                    if sibling.name == "p":
                        content_parts.append(self.clean_text(sibling.get_text()))
                content = " ".join(content_parts)
                if len(content) < 100:
                    continue
                articles.append(
                    ScrapedArticle(
                        title=title,
                        url=page_url,
                        content=content[:3000],
                        summary=content[:300],
                        published_at=datetime.now(UTC),
                        category=category,
                        tags=["academia", "armenia"],
                    )
                )

        logger.info(f"[{self.SOURCE_NAME}] Collected {len(articles)} academic sections.")
        return articles


class ArmenianHistoryOnThisDay(BaseScraper):
    """
    Generates 'on this day in Armenian history' style content by scraping
    Wikipedia's 'Armenian_history' category and date-based pages.
    """
    SOURCE_NAME = "Armenian History On This Day"
    BASE_URL = "https://en.wikipedia.org"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL)

    def scrape(self) -> list[ScrapedArticle]:
        today = datetime.now(UTC)
        month_name = today.strftime("%B")
        day = today.day
        url = f"https://en.wikipedia.org/wiki/{month_name}_{day}"

        resp = self.fetch(url)
        if not resp:
            return []

        soup = self.parse_html(resp.text)
        content_div = soup.select_one("#mw-content-text .mw-parser-output")
        if not content_div:
            return []

        articles: list[ScrapedArticle] = []
        # Find events mentioning Armenia / Armenian
        for li in content_div.find_all("li"):
            text = li.get_text(separator=" ")
            if re.search(r"\bArmenian?\b", text, re.IGNORECASE):
                year_match = re.match(r"^\s*(\d{1,4})", text)
                year = year_match.group(1) if year_match else "Unknown year"
                title = f"On this day ({month_name} {day}): {text[:120].strip()}"
                articles.append(
                    ScrapedArticle(
                        title=title,
                        url=url,
                        content=text.strip(),
                        summary=text[:400].strip(),
                        published_at=today,
                        category="history",
                        tags=["on this day", "armenian history", year],
                    )
                )

        logger.info(f"[{self.SOURCE_NAME}] Found {len(articles)} Armenian events on {month_name} {day}.")
        return articles


class HoushamadyanScraper(BaseScraper):
    """
    Scrapes Houshamadyan.org — a project reconstructing the history and
    culture of Ottoman Armenian communities; ideal for diaspora heritage posts.
    """
    SOURCE_NAME = "Houshamadyan"
    BASE_URL = "https://www.houshamadyan.org"
    SECTIONS = [
        "https://www.houshamadyan.org/en/news.html",
        "https://www.houshamadyan.org/en/mapottomanempire.html",
    ]

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL)

    def scrape(self) -> list[ScrapedArticle]:
        articles: list[ScrapedArticle] = []
        for section_url in self.SECTIONS:
            resp = self.fetch(section_url)
            if not resp:
                continue
            soup = self.parse_html(resp.text)
            for tag in soup.find_all(["nav", "footer", "script", "style"]):
                tag.decompose()
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = self.clean_text(a_tag.get_text())
                if len(text) < 15 or len(text) > 300:
                    continue
                url = href if href.startswith("http") else self.BASE_URL + href
                if self.BASE_URL.split("//")[1].split("/")[0] not in url:
                    continue
                articles.append(
                    ScrapedArticle(
                        title=text,
                        url=url,
                        summary="",
                        published_at=datetime.now(UTC),
                        category="history",
                        tags=["history", "armenia", "diaspora", "ottoman"],
                    )
                )
                if len(articles) >= 20:
                    break
            if len(articles) >= 20:
                break

        logger.info(f"[{self.SOURCE_NAME}] Collected {len(articles)} heritage links.")
        return articles


class ArmenianGenocideMuseumScraper(BaseScraper):
    """
    Scrapes the Armenian Genocide Museum-Institute (agmi.am) news and
    publications for genocide recognition and remembrance content.
    """
    SOURCE_NAME = "Armenian Genocide Museum-Institute"
    BASE_URL = "https://www.genocide-museum.am"
    NEWS_URL = "https://www.genocide-museum.am/eng/news.php"

    def __init__(self):
        super().__init__(self.SOURCE_NAME, self.BASE_URL)

    def scrape(self) -> list[ScrapedArticle]:
        resp = self.fetch(self.NEWS_URL)
        if not resp:
            return []
        soup = self.parse_html(resp.text)
        for tag in soup.find_all(["nav", "footer", "script", "style"]):
            tag.decompose()

        articles: list[ScrapedArticle] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = self.clean_text(a_tag.get_text())
            if len(text) < 15 or len(text) > 300:
                continue
            url = href if href.startswith("http") else self.BASE_URL + "/" + href.lstrip("/")
            if self.BASE_URL.split("//")[1].split("/")[0] not in url:
                continue
            articles.append(
                ScrapedArticle(
                    title=text,
                    url=url,
                    summary="",
                    published_at=datetime.now(UTC),
                    category="history",
                    tags=["armenian genocide", "history", "recognition", "armenia"],
                )
            )
            if len(articles) >= 20:
                break

        logger.info(f"[{self.SOURCE_NAME}] Collected {len(articles)} items.")
        return articles


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_HISTORY_SCRAPERS = [
    WikipediaArmenianHistoryScraper,
    HyestartScraper,
    ArmenianStudiesAcademicScraper,
    ArmenianHistoryOnThisDay,
    HoushamadyanScraper,
    ArmenianGenocideMuseumScraper,
]
