"""Tests for scraper keyword filtering — ensures Armenian content is correctly identified."""
import pytest
import re


@pytest.fixture(scope="module")
def armenian_pattern():
    """Load and compile the ARMENIAN_KEYWORDS regex from the source file."""
    with open("app/scrapers/armenian_news.py", "r") as f:
        content = f.read()
    start = content.index("ARMENIAN_KEYWORDS: list[str] = [")
    end = content.index("\n]", start) + 2
    ns: dict = {}
    exec(content[start:end], ns)
    return re.compile("|".join(ns["ARMENIAN_KEYWORDS"]), re.IGNORECASE)


class TestArmenianKeywordFilter:
    """Headlines that MUST match — covers every major category."""

    @pytest.mark.parametrize("headline", [
        # Country / basic
        "Armenia signs peace deal",
        "Armenian community celebrates",
        # Transliteration: Eastern -yan & Western -ian
        "Pashinyan visits Berlin",
        "Pashinian addresses UN",
        "Sarkissian foundation gala",
        "Kocharyan arrested again",
        "Kocharian trial resumes",
        # Cities
        "Yerevan hosts tech summit",
        "Gyumri earthquake memorial",
        # Artsakh
        "Artsakh refugees demand return",
        "Karabakh ceasefire holds",
        "Stepanakert in ruins",
        # Genocide & history
        "Armenian genocide resolution passes",
        "April 24 vigil in Times Square",
        "Medz Yeghern remembrance",
        # Earlier massacres & Ottoman oppression
        "Hamidian massacres recalled after 130 years",
        "1894 Armenian massacres in Sassoun province",
        "Adana massacre memorial unveiled",
        "1909 Cilicia pogrom survivors' descendants speak",
        "Ottoman deportation of Armenians documented",
        "Young Turks and the Armenian genocide",
        "Talaat Pasha assassination legacy revisited",
        "Enver Pasha Ottoman war plans revealed",
        "Sasna Tsrer epic performed at festival",
        "Death march through Syrian desert Armenian survivors",
        "Ottoman Bank takeover re-examined",
        # Dashnak all variants
        "Dashnaktsutyun congress opens",
        "Tashnagtzoutioun global assembly meets",
        "Dashnak rally draws thousands",
        "Tashbag protest in Beirut",
        "Tashnak youth wing expands",
        # Other parties (W. & E.)
        "Ramkavar party elects new leadership",
        "Ramgavar Azadagan conference",
        "Hnchakian centennial",
        "Henchagian heritage day",
        # Heritage sites
        "Garni temple restoration complete",
        "Haghpat monastery UNESCO funding",
        "Akhtamar church hosts first service in decades",
        "Surp Giragos church restored in Diyarbakir",
        "Ani ruins open to visitors",
        "Tatev monastery cable car breaks record",
        "Dadivank monastery preservation effort",
        "Ghazanchetsots cathedral in Shushi damaged",
        # Western Armenia
        "Kharpert descendants gather",
        "Marash survivors' oral histories published",
        "Zeytun resistance commemorated",
        # Diaspora events
        "Armenian heritage month proclaimed in LA",
        "April 24 commemoration march in DC",
        "Armenian food festival draws crowds",
        "Sardarapat memorial march",
        "May 28 Armenia independence celebration",
        # Prominent figures (Western -ian surnames)
        "Manoogian Hall renovation",
        "Krikorian honored at community gala",
        "Deukmejian legacy celebrated in Sacramento",
        "Aznavour tribute concert in Paris",
        "Serj Tankian speaks on environment",
        "System of a Down reunion announced",
        "Atom Egoyan new film premieres",
        "Hovannisian lecture series at UCLA",
        # UK Western Armenian Centre
        "Western Armenian Centre London event",
        "Hrair Hawk Khatcherian speaks at conference",
        # Church
        "Echmiadzin hosts interfaith summit",
        "Etchmiadzin pilgrimage season begins",
        "Antelias catholicosate issues statement",
        # Culture
        "Komitas legacy in classical music",
        "Gomidas Vartabed anniversary concert",
        "Khachkar art exhibition opens",
        # Modern conflict
        "44-day war anniversary marked",
        "Zangezur corridor talks stall",
    ])
    def test_should_match(self, armenian_pattern, headline):
        assert armenian_pattern.search(headline), f"MISSED: {headline}"

    @pytest.mark.parametrize("headline", [
        "Bitcoin price surges past $100k",
        "Premier League results roundup",
        "NASA launches new Mars probe",
        "Tokyo stock market closes higher",
        "French election enters second round",
        "Rain expected across the UK this weekend",
    ])
    def test_should_not_match(self, armenian_pattern, headline):
        assert not armenian_pattern.search(headline), f"FALSE POSITIVE: {headline}"
