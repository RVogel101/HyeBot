# Hye-tasion 🇦🇲

**Armenian Reddit Post Idea Generator & A/B Testing Platform**

Scrapes Armenian news media and history journals, analyzes Reddit engagement patterns, generates optimized post ideas, and implements A/B testing to continuously improve post effectiveness.

---

## Features

- **Multi-source scraping** — Armenian news (Armenpress, Asbarez, Armenian Weekly, Hetq, Mirror-Spectator, Massis Post, News.am, Lragir, Mediamax, etc.) and history/heritage sources (Wikipedia, Houshamadyan, Armenian Genocide Museum-Institute, academic portals)
- **Reddit engagement analysis** — Collects top posts from target subreddits, extracts features (title structure, keywords, sentiment, posting time), and surfaces actionable patterns
- **AI-informed post generation** — Creates Reddit post ideas modelled after high-engagement patterns
- **Approval workflow** — Review, edit, approve, or reject generated ideas via a web dashboard
- **A/B testing** — Generate multiple title variants per post, post them, track metrics, and determine statistical winners
- **Performance tracking** — Monitor score, upvote ratio, and comments over time for posted content
- **Scheduled automation** — Background jobs for scraping, data collection, analysis, and metric refreshes

## Quick Start

### 1. Install dependencies
```bash
cd Hye-tasion
pip install -r requirements.txt
```

### 2. Configure
```bash
copy .env.example .env
# Edit .env with your Reddit API credentials and preferences
```

Get Reddit API credentials at https://www.reddit.com/prefs/apps (create a "script" type app).

### 3. Run
```bash
python main.py
```

Open **http://127.0.0.1:8000** in your browser.

## Dashboard

The web interface provides:

| Tab | Purpose |
|-----|---------|
| **Dashboard** | Stats overview, quick actions, engagement recommendations |
| **Post Ideas** | Browse, review, approve/reject, and edit generated post ideas |
| **A/B Tests** | Manage active tests, post variants, refresh metrics, analyze results |
| **Engagement Analysis** | Visualize patterns — title structure, keywords, optimal posting times |
| **Sources** | View all scraped news and history sources |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Dashboard statistics |
| POST | `/api/scrape/all` | Trigger full scrape |
| POST | `/api/scrape/news` | Scrape news sources only |
| POST | `/api/scrape/history` | Scrape history sources only |
| GET | `/api/articles` | List scraped articles |
| GET | `/api/post-ideas` | List generated post ideas |
| POST | `/api/generate-ideas` | Generate new post ideas |
| POST | `/api/post-ideas/{id}/approve` | Approve (optionally with A/B test) |
| POST | `/api/post-ideas/{id}/reject` | Reject an idea |
| GET | `/api/ab-tests` | List A/B tests |
| POST | `/api/ab-tests/{id}/post-variants` | Post variants to Reddit |
| POST | `/api/ab-tests/{id}/analyze` | Analyze test results |
| POST | `/api/reddit/collect` | Collect Reddit engagement data |
| POST | `/api/reddit/analyze` | Run engagement pattern analysis |
| GET | `/api/reddit/recommendations` | Get posting recommendations |

## Architecture

```
Hye-tasion/
├── main.py                   # Entry point
├── config.yaml               # Scraping sources & settings
├── requirements.txt
├── app/
│   ├── __init__.py           # FastAPI app setup
│   ├── database.py           # SQLAlchemy engine & session
│   ├── scheduler.py          # APScheduler background jobs
│   ├── api/
│   │   └── routes.py         # All REST endpoints
│   ├── models/
│   │   ├── source.py         # Source, Article
│   │   ├── post.py           # PostIdea
│   │   ├── reddit_data.py    # RedditPost, EngagementPattern
│   │   └── ab_test.py        # ABTest, ABVariant, PostPerformance
│   ├── scrapers/
│   │   ├── base_scraper.py   # Abstract scraper with retry logic
│   │   ├── armenian_news.py  # RSS scrapers for 14 Armenian news outlets
│   │   ├── history_journals.py # Wikipedia, academic, on-this-day scrapers
│   │   └── scraping_service.py # Orchestrates scrape runs
│   ├── analysis/
│   │   ├── reddit_collector.py    # PRAW-based Reddit data collection
│   │   ├── engagement_analyzer.py # Feature extraction & pattern mining
│   │   └── post_generator.py      # Template-based post idea generation
│   └── ab_testing/
│       └── ab_framework.py   # Create tests, post variants, statistical analysis
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```

## Configuration

Edit `config.yaml` to add/remove scraping sources, adjust Reddit analysis parameters, or tune A/B testing thresholds.

Key settings in `.env`:
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — Reddit API credentials
- `TARGET_SUBREDDIT` — The subreddit to post to (default: `ArmeniansGlobal`)
- `ANALYSIS_SUBREDDITS` — Comma-separated list of subreddits to analyze for engagement patterns (default includes `ArmeniansGlobal,armenia,hayastan,...`)
- `SCRAPE_INTERVAL_MINUTES` — How often to auto-scrape (default: 60)
