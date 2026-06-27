"""End-to-end API tests via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(artifacts_present, artifacts_dir):
    if not artifacts_present:
        pytest.skip("artifacts not built")
    # Force the settings to point at the artifacts dir regardless of cwd.
    from app.core import config
    config.get_settings.cache_clear()
    settings = config.get_settings()
    settings.artifacts_dir = artifacts_dir

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        # Wait for lifespan to finish loading.
        yield c


def test_healthz(client):
    r = client.get("/api/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["artifacts_loaded"] is True


def test_recommend_happy_path(client):
    r = client.post(
        "/api/v1/recommend",
        json={
            "title": "The Dark Knight",
            "top_k": 5,
            "genres": [],
            "year_min": 1900,
            "year_max": 2026,
            "min_rating": 0.0,
            "diversify": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"]["matched"] is True
    assert 1 <= len(body["results"]) <= 5


def test_recommend_unknown_title_returns_404(client):
    r = client.post(
        "/api/v1/recommend",
        json={
            "title": "xqzklmpw gibberish",
            "top_k": 5,
            "genres": [],
            "year_min": 1900,
            "year_max": 2026,
            "min_rating": 0.0,
            "diversify": False,
        },
    )
    assert r.status_code == 404


def test_movies_search(client):
    r = client.get("/api/v1/movies/search", params={"q": "avatar", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body["hits"]) <= 3
    assert all("title" in h for h in body["hits"])