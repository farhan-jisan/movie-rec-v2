"""FastAPI lifespan: load all recommender artifacts once at startup.

This is the single place where the TF-IDF matrix, SBERT embeddings, Faiss
index, and title index are loaded into memory. They live in a module-level
`state` dict that route handlers read from — avoids re-loading per request.

In the Docker image, all of these files are baked into the image at build
time by `scripts/build_artifacts.py --force`, so startup is a pure disk read.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

import joblib
import numpy as np
from fastapi import FastAPI
from scipy.sparse import load_npz

from app.core.config import get_settings
from app.recommender.search import Recommender

logger = logging.getLogger(__name__)

# Absolute path to the artifacts directory baked into the Docker image at
# /app/app/data/artifacts (see backend/Dockerfile stage 3). Using an
# absolute path avoids any dependence on cwd / WORKDIR at startup.
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "data" / "artifacts"


def _load_artifacts(artifacts_dir: Path) -> Dict[str, Any]:
    """Read every artifact from disk and return as a dict."""
    logger.info("Loading artifacts from %s", artifacts_dir)

    movies_parquet = artifacts_dir / "movies.parquet"
    tfidf_vec = artifacts_dir / "tfidf_vectorizer.joblib"
    tfidf_mat = artifacts_dir / "tfidf_matrix.npz"
    sbert_emb = artifacts_dir / "sbert_embeddings.npy"
    faiss_idx = artifacts_dir / "faiss_index.bin"
    title_idx = artifacts_dir / "title_index.json"

    # Title index is a small JSON: list of {id, title, year}.
    with open(title_idx, "r", encoding="utf-8") as fh:
        title_index = json.load(fh)

    state: Dict[str, Any] = {
        "movies_parquet": movies_parquet,
        "tfidf_vectorizer": joblib.load(tfidf_vec),
        "tfidf_matrix": load_npz(tfidf_mat),
        "sbert_embeddings": np.load(sbert_emb),
        "title_index": title_index,
    }
    # Faiss index path stored separately — Recommender handles import.
    state["faiss_index_path"] = str(faiss_idx)
    return state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load artifacts. Shutdown: nothing to release (all in-process)."""
    settings = get_settings()
    if not settings.artifacts_ready:
        logger.warning(
            "Artifacts missing in %s. Run `python scripts/build_artifacts.py --force` "
            "before starting the API. Endpoints will return 503 until then.",
            settings.artifacts_dir,
        )
        app.state.recommender = None
        app.state.ready = False
        yield
        return

    try:
        # Prefer the absolute path (independent of cwd). Fall back to
        # settings.artifacts_dir if the absolute location is missing —
        # covers the case where someone points ARTIFACTS_DIR elsewhere.
        artifacts_path = ARTIFACTS_DIR if ARTIFACTS_DIR.exists() else settings.artifacts_dir
        logger.info("Using artifacts directory: %s", artifacts_path)
        state = _load_artifacts(artifacts_path)
        app.state.recommender = Recommender(state)
        app.state.ready = True
        logger.info("Recommender ready: %d movies indexed.", len(state["title_index"]))
    except Exception:
        logger.exception("Failed to load artifacts at startup.")
        app.state.recommender = None
        app.state.ready = False

    yield