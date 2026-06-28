"""Application configuration via pydantic-settings.

Reads from environment variables (and `.env` if present). All settings are
exposed as a singleton via `get_settings()` for testability.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded once, cached for the process lifetime."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required secrets ---------------------------------------------------
    tmdb_api_key: str = Field(default="", description="TMDB v3 API key")

    # --- CORS ---------------------------------------------------------------
    # Stored as a plain string from env (`ALLOWED_ORIGINS=a,b,c` or `"*"`).
    # The `allowed_origins` property below parses it into list[str].
    # Keeping the raw field as `str` avoids pydantic-settings' complex-type
    # JSON decode step, which fails on simple values like `"*"`.
    allowed_origins_raw: str = Field(
        default=(
            "https://movie-rec-v2-dg6okjrhj-farhan-jisaaan.vercel.app,"
            "http://localhost:5173,*"
        ),
        alias="ALLOWED_ORIGINS",
    )

    # --- Paths --------------------------------------------------------------
    # Absolute path to <backend>/app/data/artifacts/ at runtime. Uses
    # `parents[1]` (= `app/`) so the resolution is independent of cwd and
    # matches both local dev and the Docker image layout
    # (`/app/app/data/artifacts`).
    artifacts_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "data" / "artifacts"
    )

    # --- Behavior -----------------------------------------------------------
    # Default top-N for /recommend if client omits it.
    default_top_n: int = Field(default=10, ge=1, le=50)

    @property
    def allowed_origins(self) -> List[str]:
        """Parse `allowed_origins_raw` into a clean list of origins.

        Tolerates missing / empty / placeholder values by falling back to
        ``["*"]`` so the app boots even when the env var is unset or contains
        an unsubstituted template like ``https://<your-vercel-domain>.vercel.app``.
        """
        v = (self.allowed_origins_raw or "").strip()
        if not v or v == "*" or "<" in v and ">" in v:
            return ["*"]
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def artifacts_ready(self) -> bool:
        """True if all expected artifact files exist on disk."""
        expected = [
            "movies.parquet",
            "tfidf_vectorizer.joblib",
            "tfidf_matrix.npz",
            "sbert_embeddings.npy",
            "faiss_index.bin",
            "title_index.json",
        ]
        return all((self.artifacts_dir / name).exists() for name in expected)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Tests can call `.cache_clear()` to reset."""
    return Settings()