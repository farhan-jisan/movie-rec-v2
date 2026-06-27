"""Data loading + soup builder.

Port of v1's notebook cells ~1030-1900. We keep the same shape on purpose:
the v1 soup (top-3 cast + director + all genres + all keywords, Porter-stemmed
and space-collapsed) is what the user already trusted. The output of this
module feeds `scripts/build_artifacts.py`.

Public API:
    load_merged_movies(raw_dir: Path) -> pd.DataFrame
    build_soup(row: pd.Series) -> str          # called per row by build_artifacts

Schema produced:
    id, title, release_year, vote_average, vote_count, runtime, overview,
    genres: list[str], keywords: list[str], cast: list[str], director: str,
    soup: str
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, List

import pandas as pd
from nltk.stem.porter import PorterStemmer

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# JSON-column parsing
# --------------------------------------------------------------------------- #

def _convert_json_column(value: Any, key: str = "name") -> List[str]:
    """Parse the TMDB-5000 JSON-encoded list columns.

    Each row looks like '[{"id": 28, "name": "Action"}, ...]'. Empty or
    malformed cells become [].
    """
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, list):
        return []
    out: List[str] = []
    for entry in parsed:
        if isinstance(entry, dict) and entry.get(key):
            out.append(str(entry[key]))
    return out


def _convert_cast(value: Any) -> List[str]:
    """Same as _convert_json_column but preserves order (we want top-3)."""
    return _convert_json_column(value, key="name")


def _convert_crew_to_director(value: Any) -> str:
    """Pull just the director name out of the crew list."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        crew = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return ""
    if not isinstance(crew, list):
        return ""
    for member in crew:
        if isinstance(member, dict) and member.get("job") == "Director":
            return str(member.get("name", "")).strip()
    return ""


# --------------------------------------------------------------------------- #
# Stemmer + space removal (matches v1)
# --------------------------------------------------------------------------- #

_stemmer = PorterStemmer()
_space_re = re.compile(r"\s+")


def _stem_word(word: str) -> str:
    return _stemmer.stem(word.lower())


def _remove_space(word: str) -> str:
    """Strip whitespace from inside a token (e.g. 'Sci Fi' -> 'scifi')."""
    return _space_re.sub("", word).lower()


# --------------------------------------------------------------------------- #
# Soup builder — one row in, one string out
# --------------------------------------------------------------------------- #

def build_soup(row: pd.Series) -> str:
    """Concatenate the featurized tokens for a single movie.

    Tokens (in order): all genres, all keywords, top-3 cast, director.
    Each token is space-removed and lowercased so 'Sam Worthington' becomes
    a single token rather than two. We deliberately do NOT Porter-stem the
    soup itself; that happens later via the TF-IDF analyzer so both forms
    remain inspectable in the parquet for debugging.
    """
    parts: List[str] = []
    parts.extend(_remove_space(g) for g in row.get("genres", []))
    parts.extend(_remove_space(k) for k in row.get("keywords", []))
    parts.extend(_remove_space(c) for c in row.get("cast", [])[:3])
    director = row.get("director", "")
    if director:
        parts.append(_remove_space(director))
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Top-level loader
# --------------------------------------------------------------------------- #

# Columns we care about from each source CSV. Keeping the list explicit makes
# the parquet output schema predictable.
_MOVIES_COLS = [
    "id", "title", "overview", "genres", "keywords",
    "release_date", "vote_average", "vote_count", "runtime",
]
_CREDITS_COLS = ["movie_id", "cast", "crew"]


def load_merged_movies(raw_dir: Path) -> pd.DataFrame:
    """Load + merge the two TMDB-5000 CSVs from `raw_dir`.

    Drops rows with null titles or empty soups. Returns a DataFrame with the
    schema documented at module top.
    """
    raw_dir = Path(raw_dir)
    movies_path = raw_dir / "tmdb_5000_movies.csv"
    credits_path = raw_dir / "tmdb_5000_credits.csv"

    if not movies_path.exists():
        raise FileNotFoundError(f"Missing {movies_path}")
    if not credits_path.exists():
        raise FileNotFoundError(f"Missing {credits_path}")

    logger.info("Reading %s", movies_path.name)
    movies = pd.read_csv(movies_path)
    logger.info("Reading %s", credits_path.name)
    credits = pd.read_csv(credits_path)

    # TMDB uses 'id' in movies and 'movie_id' in credits — rename to merge.
    credits = credits.rename(columns={"movie_id": "id"})

    # Keep only the columns we actually use, then merge.
    movies = movies[[c for c in _MOVIES_COLS if c in movies.columns]]
    credits = credits[[c for c in _CREDITS_COLS if c in credits.columns]]
    df = movies.merge(credits, on="id", how="inner")
    logger.info("Merged rows: %d", len(df))

    # Parse JSON columns.
    df["genres"] = df["genres"].apply(_convert_json_column)
    df["keywords"] = df["keywords"].apply(_convert_json_column)
    df["cast"] = df["cast"].apply(_convert_cast)
    df["director"] = df["crew"].apply(_convert_crew_to_director)
    df = df.drop(columns=[c for c in ("crew",) if c in df.columns])

    # Extract release year (TMDB stores full date; we want the integer year).
    df["release_year"] = (
        pd.to_datetime(df["release_date"], errors="coerce")
        .dt.year
        .fillna(0)
        .astype(int)
    )
    df = df.drop(columns=[c for c in ("release_date",) if c in df.columns])

    # Drop rows missing essentials. We keep rows with empty genres/cast as
    # long as the soup is non-empty after building.
    df = df.dropna(subset=["title", "overview"])
    df["title"] = df["title"].astype(str).str.strip()
    df = df[df["title"] != ""]

    # Build the soup column.
    df["soup"] = df.apply(build_soup, axis=1)

    # Drop rows whose soup is empty — they cannot be recommended.
    before = len(df)
    df = df[df["soup"].str.strip() != ""]
    dropped = before - len(df)
    if dropped:
        logger.info("Dropped %d rows with empty soup.", dropped)

    # Stable order for downstream indexes.
    df = df.reset_index(drop=True)
    logger.info("Final dataset: %d movies.", len(df))
    return df


# --------------------------------------------------------------------------- #
# Helper used by build_artifacts.py to write the title_index.json.
# --------------------------------------------------------------------------- #

def build_title_index(df: pd.DataFrame) -> List[dict]:
    """Minimal title -> row index mapping for fuzzy lookup."""
    return [
        {"id": int(row.id), "title": row.title, "year": int(row.release_year)}
        for row in df.itertuples(index=True)
    ]