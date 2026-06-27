"""API router for /api/v1/movies/* + /api/v1/recommend.

All endpoints are thin: they validate the request, call into the recommender
or TMDB client, and shape the response per the Pydantic schemas. Heavy
logic lives in `app/recommender/*`.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.config import get_settings
from app.models.schemas import (
    MovieSearchHit,
    MovieSearchResponse,
    PosterResponse,
    QueryInfo,
    RecommendationItem,
    RecommendRequest,
    RecommendResponse,
)
from app.recommender import tmdb as tmdb_client

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/movies", tags=["movies"])
recommend_router = APIRouter(tags=["recommend"])


def _recommender_or_503(request: Request):
    """Pull the loaded Recommender off app.state, or 503 if not ready."""
    rec = getattr(request.app.state, "recommender", None)
    ready = getattr(request.app.state, "ready", False)
    if not ready or rec is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Artifacts not loaded. Run `python scripts/build_artifacts.py --force` "
                "and restart the service."
            ),
        )
    return rec


# --------------------------------------------------------------------------- #
# /movies/search
# --------------------------------------------------------------------------- #

@router.get(
    "/search",
    response_model=MovieSearchResponse,
    summary="Fuzzy title search",
    description="Returns up to `limit` candidate movies whose titles fuzzy-match `q`.",
)
def search_movies(
    request: Request,
    q: str = Query(..., min_length=1, description="Title fragment to search for."),
    limit: int = Query(8, ge=1, le=25),
):
    rec = _recommender_or_503(request)
    hits = rec.fuzzy_resolve(q, limit=limit)
    return MovieSearchResponse(
        query=q,
        results=[MovieSearchHit(**hit) for hit in hits],
    )


# --------------------------------------------------------------------------- #
# /movies/{id}/poster
# --------------------------------------------------------------------------- #

@router.get(
    "/{movie_id}/poster",
    response_model=PosterResponse,
    summary="Get a TMDB poster URL for a movie id",
    description="Returns the absolute TMDB image URL or null if the movie has no poster.",
)
def get_poster(
    request: Request,
    movie_id: int,
    width: str = Query("w500", pattern="^(w92|w154|w185|w342|w500|w780|original)$"),
):
    try:
        meta = tmdb_client.get_movie(movie_id)
    except Exception as exc:  # network / auth / rate limit
        logger.exception("TMDB poster lookup failed for id=%s", movie_id)
        raise HTTPException(status_code=502, detail=f"TMDB lookup failed: {exc}") from exc

    if meta is None:
        raise HTTPException(status_code=404, detail=f"Movie {movie_id} not found on TMDB.")

    return PosterResponse(
        movie_id=movie_id,
        poster_url=tmdb_client.poster_url(meta.get("poster_path"), width=width),
        width=width,
    )


# --------------------------------------------------------------------------- #
# /recommend
# --------------------------------------------------------------------------- #

@recommend_router.post(
    "/recommend",
    response_model=RecommendResponse,
    summary="Top-N recommendations for a title",
    description=(
        "Hybrid TF-IDF + SBERT ranking with Reciprocal Rank Fusion. "
        "Optional filters narrow by genre (AND), year range, and minimum vote average."
    ),
)
def recommend(
    request: Request,
    body: RecommendRequest,
    enrich: bool = Query(
        True,
        description="If true, hydrates each result with TMDB poster + overview. "
                    "Set to false for a fast, text-only response.",
    ),
):
    rec = _recommender_or_503(request)
    settings = get_settings()
    top_n = body.top_n or settings.default_top_n

    t0 = time.perf_counter()
    rec_out = rec.recommend(
        title=body.title,
        top_n=top_n,
        genres=body.genres,
        year_min=body.year_min,
        year_max=body.year_max,
        min_rating=body.min_rating,
    )
    t_rank_ms = (time.perf_counter() - t0) * 1000.0

    if rec_out["query"] is None:
        # Title could not be resolved.
        return RecommendResponse(query=None, results=[], debug={"reason": "title_not_found"})

    # Optionally hydrate with TMDB metadata in parallel.
    t1 = time.perf_counter()
    if enrich:
        try:
            tmdb_client.enrich_results(rec_out["results"])
        except Exception as exc:
            # Enrichment is best-effort. If TMDB is down we still return rankings.
            logger.warning("TMDB enrichment failed: %s", exc)
    t_enrich_ms = (time.perf_counter() - t1) * 1000.0

    return RecommendResponse(
        query=QueryInfo(**rec_out["query"]),
        results=[RecommendationItem(**r) for r in rec_out["results"]],
        debug={
            "rank_ms": round(t_rank_ms, 1),
            "enrich_ms": round(t_enrich_ms, 1),
            "n_results": len(rec_out["results"]),
        },
    )