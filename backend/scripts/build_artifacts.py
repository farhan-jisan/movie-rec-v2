"""Build every artifact the FastAPI service needs at startup.

Outputs (relative to app/data/artifacts/):
    movies.parquet            — merged + featurized movie rows (canonical source of truth)
    tfidf_vectorizer.joblib   — fitted TfidfVectorizer
    tfidf_matrix.npz          — sparse (n_movies, n_features) TF-IDF matrix
    sbert_embeddings.npy      — (n_movies, 384) L2-normalized SBERT embeddings
    faiss_index.bin           — IndexFlatIP over the SBERT embeddings
    title_index.json          — [{id, title, year}, ...] for RapidFuzz lookup

Usage:
    python scripts/build_artifacts.py            # skip if all artifacts exist
    python scripts/build_artifacts.py --force    # rebuild unconditionally
    python scripts/build_artifacts.py --sbert-batch-size 64

This script is invoked from the Dockerfile at image-build time so the
artifacts are baked into the image. Render deploys then skip this step.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import joblib
import numpy as np

# Path bootstrap so this script works whether you run it from the backend/
# directory or from the repo root via `python -m backend.scripts.build_artifacts`.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402
from scipy.sparse import save_npz  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

from app.recommender.data import build_title_index, load_merged_movies  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_artifacts")


ARTIFACT_FILES = [
    "movies.parquet",
    "tfidf_vectorizer.joblib",
    "tfidf_matrix.npz",
    "sbert_embeddings.npy",
    "faiss_index.bin",
    "title_index.json",
]


# --------------------------------------------------------------------------- #
# Per-artifact builders
# --------------------------------------------------------------------------- #

def _write_parquet(df: pd.DataFrame, out_dir: Path) -> Path:
    path = out_dir / "movies.parquet"
    df.to_parquet(path, index=False)
    logger.info("Wrote %s (%d rows).", path.name, len(df))
    return path


def _write_tfidf(df: pd.DataFrame, out_dir: Path) -> tuple[Path, Path]:
    """Fit TF-IDF on the soup column. Same hyperparams as the v1 plan."""
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.85,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform(df["soup"].tolist())
    vec_path = out_dir / "tfidf_vectorizer.joblib"
    mat_path = out_dir / "tfidf_matrix.npz"
    joblib.dump(vectorizer, vec_path)
    save_npz(mat_path, matrix)
    logger.info(
        "Wrote %s (vocab=%d, nnz=%d) and %s.",
        vec_path.name, len(vectorizer.vocabulary_), matrix.nnz, mat_path.name,
    )
    return vec_path, mat_path


def _write_sbert(df: pd.DataFrame, out_dir: Path, batch_size: int) -> tuple[Path, "faiss.IndexFlatIP"]:
    """Encode the soup + overview with SBERT, L2-normalize, build Faiss index.

    Sentence-BERT produces 384-d vectors for all-MiniLM-L6-v2. We L2-normalize
    so cosine similarity becomes a dot product, which is exactly what
    `IndexFlatIP` measures.
    """
    from sentence_transformers import SentenceTransformer

    logger.info("Loading SBERT model sentence-transformers/all-MiniLM-L6-v2...")
    t0 = time.perf_counter()
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    logger.info("SBERT loaded in %.1fs.", time.perf_counter() - t0)

    # Combine soup (structural features) with a short overview prefix so
    # semantically similar movies cluster even when they share no keywords.
    corpus = [
        (row.soup + " " + (row.overview or "")[:512])
        for row in df.itertuples(index=False)
    ]

    logger.info("Encoding %d documents (batch_size=%d)...", len(corpus), batch_size)
    t0 = time.perf_counter()
    embeddings = model.encode(
        corpus,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,  # L2 normalize -> cosine = dot product
        convert_to_numpy=True,
    )
    logger.info("Encoded in %.1fs. shape=%s", time.perf_counter() - t0, embeddings.shape)

    emb_path = out_dir / "sbert_embeddings.npy"
    np.save(emb_path, embeddings)
    logger.info("Wrote %s.", emb_path.name)

    # Faiss IndexFlatIP over L2-normalized vectors == exact cosine NN search.
    import faiss
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(np.ascontiguousarray(embeddings, dtype=np.float32))

    faiss_path = out_dir / "faiss_index.bin"
    faiss.write_index(index, str(faiss_path))
    logger.info("Wrote %s (%d vectors, dim=%d).", faiss_path.name, index.ntotal, dim)

    return emb_path, index


def _write_title_index(df: pd.DataFrame, out_dir: Path) -> Path:
    path = out_dir / "title_index.json"
    title_index = build_title_index(df)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(title_index, fh, ensure_ascii=False, indent=2)
    logger.info("Wrote %s (%d entries).", path.name, len(title_index))
    return path


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build recommender artifacts.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild every artifact even if it already exists on disk.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=BACKEND_DIR / "app" / "data" / "raw",
        help="Directory containing tmdb_5000_movies.csv + tmdb_5000_credits.csv.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=BACKEND_DIR / "app" / "data" / "artifacts",
        help="Output directory for all built artifacts.",
    )
    parser.add_argument(
        "--sbert-batch-size",
        type=int,
        default=64,
        help="Batch size for SBERT encoding. Lower if you see OOM.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir: Path = args.artifacts_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency check. --force bypasses it.
    if not args.force:
        present = [f for f in ARTIFACT_FILES if (out_dir / f).exists()]
        if len(present) == len(ARTIFACT_FILES):
            logger.info(
                "All %d artifacts already present in %s. Nothing to do "
                "(pass --force to rebuild).",
                len(ARTIFACT_FILES), out_dir,
            )
            return 0
        missing = [f for f in ARTIFACT_FILES if not (out_dir / f).exists()]
        if missing:
            logger.info("Will build missing artifacts: %s", missing)

    t_start = time.perf_counter()

    # 1. Load + merge + featurize. This is the single source of truth.
    df = load_merged_movies(args.raw_dir)
    if df.empty:
        logger.error("Merged dataset is empty. Aborting.")
        return 1

    # 2. Persist parquet first — other artifacts reference it conceptually.
    _write_parquet(df, out_dir)

    # 3. TF-IDF on the soup.
    _write_tfidf(df, out_dir)

    # 4. SBERT embeddings + Faiss index.
    _write_sbert(df, out_dir, batch_size=args.sbert_batch_size)

    # 5. Title index for fuzzy lookup.
    _write_title_index(df, out_dir)

    elapsed = time.perf_counter() - t_start
    logger.info("All artifacts built in %.1fs. Output: %s", elapsed, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())