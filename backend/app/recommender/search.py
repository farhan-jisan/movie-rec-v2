"""Hybrid search + ranking.

Pipeline:
    1. Fuzzy-resolve the query title to a movie row (RapidFuzz).
    2. Score every other movie with TF-IDF cosine (scikit-learn linear_kernel).
    3. Score every other movie with SBERT cosine (Faiss IndexFlatIP).
    4. Fuse the two ranked lists with Reciprocal Rank Fusion (RRF, k=60).
    5. Apply post-filters (genres / year / rating), then take top-N.

The fusion + filter logic lives in `recommend()`. Lower-level scorers are
exposed as methods for the test suite.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
from rapidfuzz import fuzz, process
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

logger = logging.getLogger(__name__)


# RRF damping constant. 60 is the value used in the original RRF paper and
# is the de-facto default in modern hybrid retrieval systems.
RRF_K = 60

# When picking candidates for fusion we over-fetch, then trim to top_n. The
# RRF math is stable across hundreds of candidates so 200 is plenty.
_RRF_CANDIDATE_POOL = 200


class Recommender:
    """Stateful recommender bound to loaded artifacts."""

    def __init__(self, state: Dict[str, Any]):
        self._state = state

        # Coerce any path-like entries to absolute Paths so file loads are
        # independent of the process cwd. Defensive: protects against callers
        # passing in a relative path like "../data/artifacts/movies.parquet".
        mp = state.get("movies_parquet")
        if mp is not None and not Path(mp).is_absolute():
            mp = (
                Path(__file__).resolve().parent.parent
                / "data"
                / "artifacts"
                / Path(mp).name
            )
        state["movies_parquet"] = mp


        # SBERT + Faiss
        self._sbert_embeddings: np.ndarray = state["sbert_embeddings"]
        self._faiss_index: faiss.IndexFlatIP = faiss.read_index(state["faiss_index_path"])

        # Title index for fuzzy lookup
        self._title_index: List[Dict[str, Any]] = state["title_index"]
        self._titles: List[str] = [t["title"] for t in self._title_index]

        # Movies dataframe — loaded lazily on first recommend() so startup
        # stays cheap. ~5 MB parquet on disk.
        self._movies_df = None  # type: ignore[var-annotated]

    # ------------------------------------------------------------------ #
    # Lazy accessor for the parquet
    # ------------------------------------------------------------------ #

    def _movies(self):
        if self._movies_df is None:
            import pandas as pd

            self._movies_df = pd.read_parquet(self._state["movies_parquet"])
        return self._movies_df

    # ------------------------------------------------------------------ #
    # Fuzzy title resolution
    # ------------------------------------------------------------------ #

    def fuzzy_resolve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return up to `limit` candidate matches sorted by fuzzy score.

        Uses RapidFuzz's token-set ratio so 'the dark knight' still hits
        'The Dark Knight Rises'. We do NOT filter by score_cutoff here —
        callers may want zero hits surfaced for UX feedback.
        """
        matches = process.extract(
            query,
            self._titles,
            scorer=fuzz.WRatio,
            limit=limit,
        )
        # matches is a list of (title, score, idx)
        return [
            {
                "title": title,
                "score": float(score),
                "index": int(idx),
                "id": self._title_index[int(idx)]["id"],
                "year": self._title_index[int(idx)].get("year"),
            }
            for title, score, idx in matches
        ]

    def resolve_to_index(self, query: str) -> Optional[int]:
        """Convenience: best fuzzy match -> row index, or None if score < 60."""
        matches = process.extractOne(
            query,
            self._titles,
            scorer=fuzz.WRatio,
            score_cutoff=60,
        )
        if matches is None:
            return None
        # matches is (title, score, idx)
        return int(matches[2])

    # ------------------------------------------------------------------ #
    # Per-modality scorers (each returns (indices, scores) of top candidates)
    # ------------------------------------------------------------------ #

    def _tfidf_scores(self, row_index: int, k: int) -> Tuple[np.ndarray, np.ndarray]:
        """TF-IDF cosine via linear_kernel. Fast for sparse matrices."""
        query_vec = self._tfidf_matrix[row_index]
        sims = linear_kernel(query_vec, self._tfidf_matrix).ravel()
        # Zero out the self-similarity so we don't recommend the query movie.
        sims[row_index] = 0.0
        # argpartition is O(n) instead of O(n log n) for full sort.
        top_k_idx = np.argpartition(-sims, kth=min(k, len(sims) - 1))[:k]
        # Return sorted by score desc.
        order = np.argsort(-sims[top_k_idx])
        return top_k_idx[order], sims[top_k_idx[order]]

    def _sbert_scores(self, row_index: int, k: int) -> Tuple[np.ndarray, np.ndarray]:
        """SBERT cosine via Faiss IndexFlatIP. Embeddings are L2-normalized."""
        query_vec = self._sbert_embeddings[row_index:row_index + 1].astype(np.float32)
        scores, indices = self._faiss_index.search(query_vec, k + 1)
        indices = indices.ravel()
        scores = scores.ravel()
        # Drop self-hit if present.
        mask = indices != row_index
        return indices[mask][:k], scores[mask][:k]

    # ------------------------------------------------------------------ #
    # Reciprocal Rank Fusion
    # ------------------------------------------------------------------ #

    @staticmethod
    def rrf_fuse(
        ranked_lists: List[List[int]],
        k: int = RRF_K,
    ) -> Dict[int, float]:
        """Combine multiple ranked lists using RRF.

        For each item, rrf_score(d) = sum over all lists of 1 / (k + rank_in_list).
        Items not present in a list contribute 0 for that list. The returned
        dict maps item index -> fused score.
        """
        scores: Dict[int, float] = {}
        for ranked in ranked_lists:
            for rank, idx in enumerate(ranked, start=1):
                scores[int(idx)] = scores.get(int(idx), 0.0) + 1.0 / (k + rank)
        return scores

    # ------------------------------------------------------------------ #
    # Post-filter
    # ------------------------------------------------------------------ #

    def _apply_filters(
        self,
        candidate_indices: List[int],
        genres: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        min_rating: Optional[float] = None,
    ) -> List[int]:
        """Apply AND-combined metadata filters. Returns filtered indices."""
        if not (genres or year_min or year_max or min_rating):
            return candidate_indices

        df = self._movies()
        wanted_genres_lower = {g.lower() for g in (genres or [])}

        keep: List[int] = []
        for idx in candidate_indices:
            row = df.iloc[idx]
            if year_min is not None and int(row.release_year) < year_min:
                continue
            if year_max is not None and int(row.release_year) > year_max:
                continue
            if min_rating is not None and float(row.vote_average) < min_rating:
                continue
            if wanted_genres_lower:
                movie_genres = {g.lower() for g in (row.genres or [])}
                if not (wanted_genres_lower & movie_genres):
                    continue
            keep.append(idx)
        return keep

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def recommend(
        self,
        title: str,
        top_n: int = 10,
        genres: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        min_rating: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Top-N recommendations for `title`.

        Returns a dict:
            {
              "query": {title, id, index},
              "results": [{index, id, title, score, tfidf_rank, sbert_rank,
                           reason_tags: list[str]}, ...],
            }

        If the title cannot be resolved, returns {"query": None, "results": []}.
        """
        row_index = self.resolve_to_index(title)
        if row_index is None:
            return {"query": None, "results": []}

        df = self._movies()
        qrow = df.iloc[row_index]

        # Over-fetch so post-filter has headroom.
        k = max(top_n * 4, _RRF_CANDIDATE_POOL)

        tfidf_idx, tfidf_sims = self._tfidf_scores(row_index, k)
        sbert_idx, sbert_sims = self._sbert_scores(row_index, k)

        fused = self.rrf_fuse([tfidf_idx.tolist(), sbert_idx.tolist()])

        # Track ranks for the response payload.
        tfidf_rank_lookup = {int(idx): rank + 1 for rank, idx in enumerate(tfidf_idx)}
        sbert_rank_lookup = {int(idx): rank + 1 for rank, idx in enumerate(sbert_idx)}

        # Sort fused candidates by score desc, then apply filters.
        sorted_candidates = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
        sorted_idx = [idx for idx, _ in sorted_candidates]
        filtered_idx = self._apply_filters(
            sorted_idx, genres=genres, year_min=year_min,
            year_max=year_max, min_rating=min_rating,
        )

        results: List[Dict[str, Any]] = []
        for idx in filtered_idx[:top_n]:
            row = df.iloc[int(idx)]
            results.append(
                {
                    "index": int(idx),
                    "id": int(row.id),
                    "title": str(row.title),
                    "year": int(row.release_year),
                    "vote_average": float(row.vote_average),
                    "score": float(fused[idx]),
                    "tfidf_rank": tfidf_rank_lookup.get(int(idx)),
                    "sbert_rank": sbert_rank_lookup.get(int(idx)),
                    "reason_tags": _reason_tags(qrow, row),
                }
            )

        return {
            "query": {
                "title": str(qrow.title),
                "id": int(qrow.id),
                "index": int(row_index),
            },
            "results": results,
        }


# --------------------------------------------------------------------------- #
# Reason tags — short human-readable signals for the UI.
# --------------------------------------------------------------------------- #

def _reason_tags(query_row, candidate_row) -> List[str]:
    """Build 1-3 short strings explaining why a recommendation was made.

    Tags are derived from overlap in genres / keywords / director / cast
    between the query and the candidate. Cheap to compute and useful for
    UI sidebars ('Because it shares the director').
    """
    tags: List[str] = []

    q_genres = {g.lower() for g in (query_row.genres or [])}
    c_genres = {g.lower() for g in (candidate_row.genres or [])}
    shared_genres = q_genres & c_genres
    if shared_genres:
        shown = sorted(shared_genres)[:2]
        tags.append(f"shares genres: {', '.join(shown)}")

    if (
        query_row.director
        and candidate_row.director
        and query_row.director.lower() == candidate_row.director.lower()
    ):
        tags.append(f"same director ({query_row.director})")

    q_cast = {c.lower() for c in (query_row.cast or [])[:5]}
    c_cast = {c.lower() for c in (candidate_row.cast or [])[:5]}
    shared_cast = q_cast & c_cast
    if shared_cast:
        tags.append(f"shares cast: {', '.join(sorted(shared_cast)[:2])}")

    # Keep the tag list tight for UI display.
    return tags[:3]