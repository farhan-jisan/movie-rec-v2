"""Evaluation harness for the hybrid recommender.

Two metrics:
    Precision@K
        A returned movie counts as 'relevant' iff its genre-Jaccard with the
        query movie's genres is >= GENRE_JACCARD_THRESHOLD. P@K = #relevant / K.

    Intra-list diversity
        1 - mean(pairwise_cosine(recommended SBERT embeddings)).
        Higher means the recommendations are more varied.

Input:
    evaluation/queries.json — list of {title, expected_genres?}.
    The artifact dir must already be populated (run build_artifacts.py first).

Usage:
    python -m evaluation.eval
    python -m evaluation.eval --top-k 10 --output results.csv
    python -m evaluation.eval --ground-truth genre    # default
    python -m evaluation.eval --ground-truth tmdb     # uses TMDB /movie/{id}/similar (TODO)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Path bootstrap so this script works from any cwd.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.recommender.search import Recommender  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval")


GENRE_JACCARD_THRESHOLD = 0.5
QUERIES_PATH = Path(__file__).resolve().parent / "queries.json"
ARTIFACTS_DIR = ROOT / "backend" / "app" / "data" / "artifacts"


# --------------------------------------------------------------------------- #
# Metric helpers
# --------------------------------------------------------------------------- #

def _genre_jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = {g.lower() for g in a}, {g.lower() for g in b}
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def precision_at_k(
    query_genres: List[str],
    recommended_genres_list: List[List[str]],
    k: int,
    threshold: float = GENRE_JACCARD_THRESHOLD,
) -> float:
    """Fraction of the top-K recommendations whose genres overlap >= threshold."""
    if k <= 0 or not recommended_genres_list:
        return 0.0
    top_k = recommended_genres_list[:k]
    relevant = sum(
        1 for rec_genres in top_k
        if _genre_jaccard(query_genres, rec_genres) >= threshold
    )
    return relevant / k


def intra_list_diversity(
    recommended_embeddings: np.ndarray,
) -> float:
    """1 - mean pairwise cosine similarity. Higher = more diverse."""
    if recommended_embeddings.shape[0] < 2:
        return 0.0
    # Vectors are L2-normalized, so dot product == cosine.
    sim_matrix = recommended_embeddings @ recommended_embeddings.T
    n = sim_matrix.shape[0]
    # Exclude diagonal (self-similarity = 1).
    iu = np.triu_indices(n, k=1)
    mean_sim = float(sim_matrix[iu].mean()) if iu[0].size else 0.0
    return max(0.0, 1.0 - mean_sim)


# --------------------------------------------------------------------------- #
# Main harness
# --------------------------------------------------------------------------- #

def _load_state(artifacts_dir: Path) -> Dict[str, Any]:
    """Minimal artifact loader — separate from FastAPI's lifespan so the eval
    script doesn't need a running web server."""
    import joblib
    from scipy.sparse import load_npz

    state: Dict[str, Any] = {
        "movies_parquet": artifacts_dir / "movies.parquet",
        "tfidf_vectorizer": joblib.load(artifacts_dir / "tfidf_vectorizer.joblib"),
        "tfidf_matrix": load_npz(artifacts_dir / "tfidf_matrix.npz"),
        "sbert_embeddings": np.load(artifacts_dir / "sbert_embeddings.npy"),
        "faiss_index_path": str(artifacts_dir / "faiss_index.bin"),
        "title_index": json.loads(
            (artifacts_dir / "title_index.json").read_text(encoding="utf-8")
        ),
    }
    return state


def run_eval(args: argparse.Namespace) -> int:
    if not QUERIES_PATH.exists():
        logger.error("Missing query set: %s", QUERIES_PATH)
        return 2
    if not (ARTIFACTS_DIR / "movies.parquet").exists():
        logger.error(
            "Artifacts not built. Run: python backend/scripts/build_artifacts.py --force"
        )
        return 2

    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded %d queries from %s", len(queries), QUERIES_PATH.name)

    state = _load_state(ARTIFACTS_DIR)
    rec = Recommender(state)
    df = rec._movies()  # pylint: disable=protected-access

    rows: List[Dict[str, Any]] = []

    for q in queries:
        title = q["title"]
        out = rec.recommend(title=title, top_n=args.top_k)
        if out["query"] is None:
            logger.warning("Could not resolve query: %r — skipping.", title)
            rows.append({
                "query": title,
                "resolved": False,
                "p_at_k": None,
                "diversity": None,
                "n_results": 0,
            })
            continue

        query_genres = df.iloc[out["query"]["index"]].genres or []
        rec_idxs = [r["index"] for r in out["results"]]
        rec_genres_list = [df.iloc[i].genres or [] for i in rec_idxs]
        rec_embeds = rec._sbert_embeddings[rec_idxs]  # pylint: disable=protected-access

        p_at_k = precision_at_k(query_genres, rec_genres_list, k=args.top_k)
        diversity = intra_list_diversity(rec_embeds)

        rows.append({
            "query": title,
            "resolved": True,
            "p_at_k": round(p_at_k, 3),
            "diversity": round(diversity, 3),
            "n_results": len(out["results"]),
        })
        logger.info(
            "%-30s  P@%d=%.3f  diversity=%.3f  (n=%d)",
            title, args.top_k, p_at_k, diversity, len(out["results"]),
        )

    # Aggregate. Only count resolved queries in the mean.
    resolved = [r for r in rows if r["resolved"]]
    if resolved:
        mean_p = float(np.mean([r["p_at_k"] for r in resolved]))
        mean_d = float(np.mean([r["diversity"] for r in resolved]))
    else:
        mean_p = mean_d = 0.0

    print("\n" + "=" * 70)
    print(f"Evaluated {len(resolved)}/{len(queries)} queries (top_k={args.top_k})")
    print(f"Mean Precision@{args.top_k}: {mean_p:.3f}")
    print(f"Mean Intra-list Diversity : {mean_d:.3f}")
    print("=" * 70)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
            writer.writerow({
                "query": "MEAN",
                "resolved": "",
                "p_at_k": round(mean_p, 3),
                "diversity": round(mean_d, 3),
                "n_results": sum(r["n_results"] for r in rows),
            })
        logger.info("Wrote %s.", out_path)

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the hybrid recommender.")
    parser.add_argument("--top-k", type=int, default=10, help="K for Precision@K.")
    parser.add_argument(
        "--ground-truth",
        choices=["genre", "tmdb"],
        default="genre",
        help="Relevance signal: genre Jaccard (default) or TMDB /similar (TODO).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="If set, write a per-query CSV to this path.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=ARTIFACTS_DIR,
        help="Where to read the built artifacts from.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.ground_truth == "tmdb":
        logger.warning(
            "--ground-truth=tmdb is not implemented yet; falling back to genre."
        )
        args.ground_truth = "genre"
    return run_eval(args)


if __name__ == "__main__":
    raise SystemExit(main())