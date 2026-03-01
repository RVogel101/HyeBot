"""Tests for the API routes — authentication, CRUD, and edge cases."""
import pytest


API_KEY = "test-secret-key"
HEADERS = {"X-API-Key": API_KEY}


# ─── Authentication ────────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_key_returns_401(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"].lower() or "api" in resp.json()["detail"].lower()

    def test_wrong_key_returns_401(self, client):
        resp = client.get("/api/stats", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_valid_key_returns_200(self, client):
        resp = client.get("/api/stats", headers=HEADERS)
        assert resp.status_code == 200


# ─── Dashboard stats ──────────────────────────────────────────────────────────

class TestDashboard:
    def test_stats_empty_db(self, client):
        resp = client.get("/api/stats", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == 0
        assert data["articles_scraped"] == 0
        assert data["post_ideas"]["total"] == 0

    def test_stats_with_data(self, client, make_source, make_article):
        src = make_source()
        make_article(source=src, title="A1")
        make_article(source=src, title="A2", url="https://example.com/a2")
        resp = client.get("/api/stats", headers=HEADERS)
        data = resp.json()
        assert data["sources"] == 1
        assert data["articles_scraped"] == 2


# ─── Sources ──────────────────────────────────────────────────────────────────

class TestSources:
    def test_list_sources_empty(self, client):
        resp = client.get("/api/sources", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_sources(self, client, make_source):
        make_source(name="Armenpress", url="https://armenpress.am")
        resp = client.get("/api/sources", headers=HEADERS)
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Armenpress"


# ─── Articles ─────────────────────────────────────────────────────────────────

class TestArticles:
    def test_list_articles_pagination(self, client, make_source, make_article):
        src = make_source()
        for i in range(5):
            make_article(source=src, title=f"Art {i}", url=f"https://example.com/{i}")
        resp = client.get("/api/articles?limit=2", headers=HEADERS)
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

    def test_list_articles_filter_category(self, client, make_source, make_article):
        src = make_source()
        make_article(source=src, title="News", category="news")
        make_article(source=src, title="History", url="https://example.com/h", category="history")
        resp = client.get("/api/articles?category=history", headers=HEADERS)
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "history"


# ─── Post ideas CRUD ──────────────────────────────────────────────────────────

class TestPostIdeas:
    def test_list_empty(self, client):
        resp = client.get("/api/post-ideas", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_get_not_found(self, client):
        resp = client.get("/api/post-ideas/999", headers=HEADERS)
        assert resp.status_code == 404

    def test_patch_idea(self, client, make_post_idea):
        idea = make_post_idea(title="Original")
        resp = client.patch(
            f"/api/post-ideas/{idea.id}",
            json={"title": "Updated Title"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    def test_patch_title_too_long(self, client, make_post_idea):
        idea = make_post_idea()
        resp = client.patch(
            f"/api/post-ideas/{idea.id}",
            json={"title": "x" * 301},
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_reject_idea(self, client, make_post_idea):
        idea = make_post_idea()
        resp = client.post(
            f"/api/post-ideas/{idea.id}/reject",
            json={"reason": "Not relevant"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_approve_creates_ab_test(self, client, db, make_post_idea):
        idea = make_post_idea()
        resp = client.post(
            f"/api/post-ideas/{idea.id}/approve",
            json={"create_ab_test": True, "num_ab_variants": 2},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert "ab_test_id" in data


# ─── A/B tests ────────────────────────────────────────────────────────────────

class TestABTests:
    def test_list_empty(self, client):
        resp = client.get("/api/ab-tests", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_not_found(self, client):
        resp = client.get("/api/ab-tests/999", headers=HEADERS)
        assert resp.status_code == 404

    def test_get_with_variants(self, client, make_ab_test):
        test = make_ab_test()
        resp = client.get(f"/api/ab-tests/{test.id}", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["variants"]) == 2
        assert data["is_active"] is True


# ─── Reddit data ──────────────────────────────────────────────────────────────

class TestRedditEndpoints:
    def test_list_posts_empty(self, client):
        resp = client.get("/api/reddit/posts", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_patterns_empty(self, client):
        resp = client.get("/api/reddit/patterns", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []
