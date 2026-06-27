"""TMDB v3 API client.

Thin synchronous wrapper around the three endpoints we actually need:
    GET /3/search/movie           — by query string
    GET /3/movie/{id}             — full metadata
    GET /3/movie/{id}/credits     — cast + crew

We use `requests` (not httpx) because all calls are short and we can comfortably
run them in `concurrent.futures.ThreadPoolExecutor` for parallelism. Tenacity
retries on 429 / 5xx with exponential backoff.

Public API:
    poster_url(poster_path, width="w500") -> str
    search_movie(query, limit=10)        -> list[dict]
    get_movie(movie_id)                   -> dict | None
    get_credits(movie_id)                 -> dict | None
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
DEFAULT_TIMEOUT_SECONDS = 8.0

# Status codes worth retrying. 429 is rate-limited, 5xx is server hiccup.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class TMDBError(Exception):
    """Base TMDB error."""


class TMDBAuthError(TMDBError):
    """Missing or invalid API key."""


class TMDBNotFound(TMDBError):
    """Resource does not exist (404). Not retried."""


class TMDBRateLimited(TMDBError):
    """Returned after retry exhaustion on 429."""


class TMDBUnavailable(TMDBError):
    """Returned after retry exhaustion on 5xx."""


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _api_key() -> str:
    """Fetch the API key lazily so tests can set it after import."""
    key = get_settings().tmdb_api_key
    if not key:
        raise TMDBAuthError(
            "TMDB_API_KEY is not set. Add it to backend/.env or the Render env."
        )
    return key


def _retrying_request(method: str, path: str, **params) -> Dict[str, Any]:
    """GET request with retries. Returns parsed JSON or raises."""
    url = f"{TMDB_BASE}{path}"
    params = {**params, "api_key": _api_key()}

    # Tenacity decorator: 3 attempts, exponential backoff 1s -> 2s -> 4s.
    @retry(
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _do() -> Dict[str, Any]:
        try:
            resp = requests.request(
                method, url, params=params, timeout=DEFAULT_TIMEOUT_SECONDS
            )
        except requests.exceptions.RequestException as exc:
            # Network-level failure: retry.
            logger.warning("TMDB network error on %s: %s", path, exc)
            raise

        if resp.status_code == 404:
            raise TMDBNotFound(f"{path} not found")
        if resp.status_code == 401 or resp.status_code == 403:
            raise TMDBAuthError(f"TMDB auth failed ({resp.status_code})")
        if resp.status_code in RETRYABLE_STATUSES:
            logger.warning(
                "TMDB retryable %s on %s (status %s); will retry.",
                method, path, resp.status_code,
            )
            if resp.status_code == 429:
                raise TMDBRateLimited(f"TMDB 429 on {path}")
            raise TMDBUnavailable(f"TMDB {resp.status_code} on {path}")
        if not resp.ok:
            raise TMDBError(f"TMDB {resp.status_code} on {path}: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise TMDBError(f"TMDB returned non-JSON on {path}: {exc}") from exc

    return _do()


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #

def poster_url(poster_path: Optional[str], width: str = "w500") -> Optional[str]:
    """Compose the full TMDB image URL. Returns None if poster_path is falsy."""
    if not poster_path:
        return None
    # TMDB accepts sizes: w92, w154, w185, w342, w500, w780, original.
    return f"{TMDB_IMAGE_BASE}/{width}/{poster_path.lstrip('/')}"


def search_movie(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search TMDB by free-text query. Returns up to `limit` results."""
    if not query or not query.strip():
        return []
    data = _retrying_request("GET", "/search/movie", query=query.strip())
    results = data.get("results", [])
    return results[:limit]


def get_movie(movie_id: int) -> Optional[Dict[str, Any]]:
    """Fetch full metadata for a movie. Returns None if not found."""
    try:
        return _retrying_request("GET", f"/movie/{movie_id}")
    except TMDBNotFound:
        return None


def get_credits(movie_id: int) -> Optional[Dict[str, Any]]:
    """Fetch cast + crew for a movie. Returns None if not found."""
    try:
        return _retrying_request("GET", f"/movie/{movie_id}/credits")
    except TMDBNotFound:
        return None


def enrich_results(
    results: List[Dict[str, Any]],
    include_credits: bool = False,
) -> List[Dict[str, Any]]:
    """Hydrate recommendation rows with TMDB poster + metadata.

    Designed for the API layer: takes the slim dicts from `recommend()` and
    returns the same dicts augmented with `poster_url`, `overview`, etc.
    Done in parallel via threads because each call is I/O bound.
    """
    from concurrent.futures import ThreadPoolExecutor

    if not results:
        return results

    movie_ids = [r["id"] for r in results]

    def _fetch(rid: int):
        return rid, get_movie(rid)

    with ThreadPoolExecutor(max_workers=min(10, len(movie_ids))) as pool:
        metadata = dict(pool.map(_fetch, movie_ids))

    for r in results:
        meta = metadata.get(r["id"])
        if not meta:
            r["poster_url"] = None
            r["overview"] = None
            r["runtime"] = None
            continue
        r["poster_url"] = poster_url(meta.get("poster_path"))
        r["overview"] = meta.get("overview")
        r["runtime"] = meta.get("runtime")
        r["tagline"] = meta.get("tagline")
    return results