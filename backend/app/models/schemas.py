"""Pydantic v2 request/response schemas for the public API.

Mirrored on the frontend in `frontend/src/lib/types.ts`.  Keep both files
in sync when a field is added, renamed, or removed.

Schema map
----------
- `MovieSearchHit` / `MovieSearchResponse`  : GET /api/v1/movies/search
- `PosterResponse`                          : GET /api/v1/movies/{id}/poster
- `RecommendRequest` / `RecommendResponse`  : POST /api/v1/recommend
- `QueryInfo` / `RecommendationItem`        : sub-models for RecommendResponse
- `HealthzResponse`                         : GET /api/v1/healthz
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# /api/v1/healthz
# --------------------------------------------------------------------------- #

class HealthzResponse(BaseModel):
    """Lightweight liveness probe.

    `artifacts_loaded=False` means the lifespan loader hasn't finished yet
    (cold start) or build_artifacts.py hasn't been run.
    """

    status: str = Field(..., description="'ok' once the service is ready.")
    artifacts_loaded: bool = Field(
        ...,
        description="True if the Recommender has been constructed from on-disk artifacts.",
    )
    n_movies: Optional[int] = Field(
        None,
        description="Number of movies loaded into the in-memory recommender.",
    )


# --------------------------------------------------------------------------- #
# /api/v1/movies/search
# --------------------------------------------------------------------------- #

class MovieSearchHit(BaseModel):
    """A single fuzzy-matched title from `Recommender.fuzzy_resolve`."""

    title: str = Field(..., description="Movie title exactly as indexed.")
    id: int = Field(..., description="TMDB movie id.")
    index: int = Field(..., description="Row index into the internal parquet.")
    score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="RapidFuzz WRatio score (0-100). Higher is better.",
    )
    year: Optional[int] = Field(
        None,
        description="Release year; null if the source row was missing a date.",
    )


class MovieSearchResponse(BaseModel):
    """Result wrapper for the search endpoint."""

    query: str = Field(..., description="The original query string.")
    results: List[MovieSearchHit] = Field(
        default_factory=list,
        description="Up to `limit` fuzzy-matched titles, sorted by score desc.",
    )


# --------------------------------------------------------------------------- #
# /api/v1/movies/{id}/poster
# --------------------------------------------------------------------------- #

class PosterResponse(BaseModel):
    """A poster URL for a given movie id, at a specific TMDB image width."""

    movie_id: int = Field(..., description="TMDB movie id.")
    poster_url: Optional[str] = Field(
        None,
        description="Absolute poster URL, or null if the movie has no poster on TMDB.",
    )
    width: str = Field(
        ...,
        description="TMDB image width key (w92 | w154 | w185 | w342 | w500 | w780 | original).",
    )


# --------------------------------------------------------------------------- #
# /api/v1/recommend
# --------------------------------------------------------------------------- #

class RecommendRequest(BaseModel):
    """Body for POST /api/v1/recommend."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "The Dark Knight",
                "top_n": 10,
                "genres": ["Action", "Crime"],
                "year_min": 1990,
                "year_max": 2026,
                "min_rating": 6.0,
            }
        }
    )

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Title (or fragment) to seed the recommendation.",
    )
    top_n: Optional[int] = Field(
        None,
        ge=1,
        le=50,
        description="Override the default top-N. If null, the server default applies.",
    )
    genres: List[str] = Field(
        default_factory=list,
        description="AND-combined genre filter; empty list = no genre filter.",
    )
    year_min: int = Field(
        1900,
        ge=1900,
        le=2100,
        description="Earliest release year to include.",
    )
    year_max: int = Field(
        2100,
        ge=1900,
        le=2100,
        description="Latest release year to include.",
    )
    min_rating: float = Field(
        0.0,
        ge=0.0,
        le=10.0,
        description="Minimum TMDB vote_average to include.",
    )
    diversify: bool = Field(
        False,
        description="If true, apply MMR-style diversification to the top-N.",
    )


class QueryInfo(BaseModel):
    """Echo of the resolved seed title returned with every successful recommend."""

    title: str = Field(..., description="The title after fuzzy resolution.")
    id: int = Field(..., description="TMDB id of the resolved title.")
    index: int = Field(..., description="Row index into the internal parquet.")


class RecommendationItem(BaseModel):
    """One row of the recommendation response.

    Fields marked Optional are populated by `tmdb.enrich_results` after
    ranking; if enrichment fails or is disabled, they may be null.
    """

    index: int = Field(..., description="Row index into the internal parquet.")
    id: int = Field(..., description="TMDB movie id.")
    title: str = Field(..., description="Movie title.")
    year: int = Field(..., description="Release year.")
    vote_average: float = Field(..., description="TMDB vote_average (0-10).")
    score: float = Field(
        ...,
        description="Final RRF-fused score (higher is more similar).",
    )
    tfidf_rank: Optional[int] = Field(
        None,
        description="Rank from the TF-IDF candidate list (1-based), or null if not in top-K.",
    )
    sbert_rank: Optional[int] = Field(
        None,
        description="Rank from the SBERT candidate list (1-based), or null if not in top-K.",
    )
    reason_tags: List[str] = Field(
        default_factory=list,
        description="1-3 short strings explaining why this was recommended.",
    )

    # TMDB-enriched fields. Optional because they may be absent when
    # enrichment is disabled or TMDB is unreachable.
    poster_url: Optional[str] = Field(
        None,
        description="Absolute TMDB poster URL (enrichment only).",
    )
    overview: Optional[str] = Field(
        None,
        description="TMDB overview blurb (enrichment only).",
    )
    runtime: Optional[int] = Field(
        None,
        description="Runtime in minutes (enrichment only).",
    )
    tagline: Optional[str] = Field(
        None,
        description="TMDB tagline (enrichment only).",
    )


class RecommendResponse(BaseModel):
    """Top-level response for POST /api/v1/recommend."""

    query: Optional[QueryInfo] = Field(
        None,
        description="Resolved query info; null if the title could not be resolved.",
    )
    results: List[RecommendationItem] = Field(
        default_factory=list,
        description="Up to `top_n` recommendations, sorted by score desc.",
    )
    debug: Dict[str, Any] = Field(
        default_factory=dict,
        description="Timing + count telemetry. Keys: rank_ms, enrich_ms, n_results, reason.",
    )