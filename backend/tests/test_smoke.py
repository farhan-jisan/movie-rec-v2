"""Smoke test: every expected artifact must be loadable + have plausible shape."""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
import pytest
from scipy.sparse import load_npz

from tests.conftest import EXPECTED_ARTIFACTS


@pytest.mark.skipif(
    "not config.getoption('--with-artifacts')",
    reason="artifacts not built; run `python scripts/build_artifacts.py --force` first",
)
def test_artifacts_present(artifacts_dir):
    for name in EXPECTED_ARTIFACTS:
        assert (artifacts_dir / name).exists(), f"missing artifact: {name}"


def test_artifacts_loadable(artifacts_present, artifacts_dir):
    if not artifacts_present:
        pytest.skip("artifacts not built")

    # Parquet: dataframe with at least the columns downstream expects.
    df = pd.read_parquet(artifacts_dir / "movies.parquet")
    expected_cols = {"id", "title", "genres", "soup"}
    assert expected_cols <= set(df.columns), f"parquet missing columns: {expected_cols - set(df.columns)}"
    assert len(df) > 1000, f"parquet too small: {len(df)} rows"

    # TF-IDF: matrix and vectorizer agree on shape.
    tfidf_matrix = load_npz(artifacts_dir / "tfidf_matrix.npz")
    vectorizer = joblib.load(artifacts_dir / "tfidf_vectorizer.joblib")
    assert tfidf_matrix.shape[0] == len(df), "tfidf rows != parquet rows"
    assert tfidf_matrix.shape[1] == len(vectorizer.vocabulary_), "tfidf cols != vocab"

    # SBERT: 384-d MiniLM embeddings, rows match.
    sbert = np.load(artifacts_dir / "sbert_embeddings.npy")
    assert sbert.shape == (len(df), 384), f"unexpected sbert shape: {sbert.shape}"

    # Title index: dict[str, int].
    with open(artifacts_dir / "title_index.json") as f:
        title_index = json.load(f)
    assert isinstance(title_index, dict)
    assert len(title_index) > 1000


def test_recommender_constructs(artifacts_present):
    if not artifacts_present:
        pytest.skip("artifacts not built")

    from app.recommender.search import Recommender

    state = {
        "parquet_path": artifacts_dir := __import__("pathlib").Path("app/data/artifacts/movies.parquet"),
        "tfidf_vectorizer_path": artifacts_dir.parent / "tfidf_vectorizer.joblib",
        "tfidf_matrix_path": artifacts_dir.parent / "tfidf_matrix.npz",
        "sbert_embeddings_path": artifacts_dir.parent / "sbert_embeddings.npy",
        "faiss_index_path": artifacts_dir.parent / "faiss_index.bin",
        "title_index_path": artifacts_dir.parent / "title_index.json",
    }
    rec = Recommender(state)
    assert rec.n_movies > 1000
    assert rec.title_index_size > 1000