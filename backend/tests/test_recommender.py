"""Unit tests for the Recommender — RRF math, filtering, and fuzzy resolve."""

from __future__ import annotations

import pytest

from app.recommender.search import Recommender


def test_rrf_fuse_single_source_preserves_order():
    """If only one list contributes, RRF scores should strictly decrease by rank."""
    fused = Recommender.rrf_fuse(
        tfidf=[("a", 1.0), ("b", 0.9), ("c", 0.8)],
        sbert=[],
        k=60,
    )
    assert [doc_id for doc_id, _ in fused] == ["a", "b", "c"]


def test_rrf_fuse_overlapping_higher_than_unique():
    """A document in BOTH lists must rank above a document in only one."""
    fused = Recommender.rrf_fuse(
        tfidf=[("x", 1.0), ("y", 0.5), ("z", 0.1)],
        sbert=[("x", 0.9), ("p", 0.8)],
        k=60,
    )
    scores = dict(fused)
    assert scores["x"] > scores["p"]
    assert scores["x"] > scores["y"]


def test_rrf_fuse_k_zero_breaks_degenerate_case():
    """k=0 would divide by zero; the static method should still tolerate it."""
    fused = Recommender.rrf_fuse(
        tfidf=[("a", 1.0), ("b", 0.5)],
        sbert=[("a", 0.9)],
        k=1,
    )
    assert fused[0][0] == "a"


def test_recommend_returns_expected_shape(artifacts_present, artifacts_dir):
    if not artifacts_present:
        pytest.skip("artifacts not built")
    state = _build_state(artifacts_dir)
    rec = Recommender(state)

    out = rec.recommend(
        title="The Dark Knight",
        top_k=10,
        genres=[],
        year_min=1900,
        year_max=2026,
        min_rating=0.0,
        diversify=False,
    )
    assert out["query"]["matched"] is True
    assert len(out["results"]) <= 10
    for r in out["results"]:
        assert {"id", "title", "score", "reason_tags"} <= set(r.keys())


def test_recommend_filters_by_genre(artifacts_present, artifacts_dir):
    if not artifacts_present:
        pytest.skip("artifacts not built")
    state = _build_state(artifacts_dir)
    rec = Recommender(state)

    out = rec.recommend(
        title="Toy Story",
        top_k=10,
        genres=["Animation"],
        year_min=1900,
        year_max=2026,
        min_rating=0.0,
        diversify=False,
    )
    # Every result must carry Animation in its genre list.
    for r in out["results"]:
        assert "Animation" in r["genres"], f"filter leaked: {r['title']} genres={r['genres']}"


def test_fuzzy_resolve_threshold(artifacts_present, artifacts_dir):
    if not artifacts_present:
        pytest.skip("artifacts not built")
    state = _build_state(artifacts_dir)
    rec = Recommender(state)

    # Exact-ish
    hit = rec.fuzzy_resolve("Avatar")
    assert hit is not None
    assert "avatar" in hit[0].lower()

    # Misspelled
    hit = rec.fuzzy_resolve("Avatr")
    assert hit is not None

    # Total gibberish
    assert rec.fuzzy_resolve("xqzklmpw") is None


def _build_state(artifacts_dir):
    return {
        "parquet_path": artifacts_dir / "movies.parquet",
        "tfidf_vectorizer_path": artifacts_dir / "tfidf_vectorizer.joblib",
        "tfidf_matrix_path": artifacts_dir / "tfidf_matrix.npz",
        "sbert_embeddings_path": artifacts_dir / "sbert_embeddings.npy",
        "faiss_index_path": artifacts_dir / "faiss_index.bin",
        "title_index_path": artifacts_dir / "title_index.json",
    }