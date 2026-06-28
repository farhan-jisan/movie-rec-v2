"""Application configuration via pydantic-settings.

Reads from environment variables (and `.env` if present). All settings are
exposed as a singleton via `get_settings()` for testability.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    # Comma-separated string in env, parsed to list[str].
    # `NoDecode` stops pydantic-settings from trying to JSON-parse the raw
    # env value (which fails for plain strings like "*"). The
    # `mode="before"` validator below handles string→list conversion.
    allowed_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["*"]
    )

    # --- Paths --------------------------------------------------------------
    # Defaults to <repo>/backend/app/data/artifacts/ at runtime.
    artifacts_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "app" / "data" / "artifacts"
    )

    # --- Behavior -----------------------------------------------------------
    # Default top-N for /recommend if client omits it.
    default_top_n: int = Field(default=10, ge=1, le=50)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """Allow comma-separated string from env (e.g. ALLOWED_ORIGINS=a,b,c).

        Tolerate missing / empty / placeholder values by falling back to ["*"]
        so the app boots even when the env var is unset or contains a
        unsubstituted template like ``https://<your-vercel-domain>.vercel.app``.
        """
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped or "<" in stripped and ">" in stripped:
                return ["*"]
            return [o.strip() for o in stripped.split(",") if o.strip()]
        return v

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