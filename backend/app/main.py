"""FastAPI app entry point.

Wires CORS, the lifespan artifact-loader, and the v1 API router. Exposes
`/api/v1/healthz` for liveness probes and cold-start warmups.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.movies import router as movies_router, recommend_router
from app.core.config import get_settings
from app.core.lifespan import lifespan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Movie Recommender v2 API",
        version="0.1.0",
        description=(
            "TMDB-5000 content-based recommender. Hybrid TF-IDF + SBERT with "
            "Reciprocal Rank Fusion, Faiss cosine index, RapidFuzz fuzzy search, "
            "and TMDB v3 metadata proxy."
        ),
        lifespan=lifespan,
    )

    # CORS — must allow the Vercel frontend origin(s) and localhost for dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(movies_router, prefix="/api/v1")
    app.include_router(recommend_router, prefix="/api/v1")

    @app.get("/api/v1/healthz", tags=["meta"], include_in_schema=True)
    def healthz():
        """Lightweight liveness + artifact readiness probe.

        Used by:
          - Render for liveness checks.
          - The React frontend's silent mount-time ping to mask Render's
            free-tier cold start (~1 min spin-up after 15 min idle).
        """
        ready = getattr(app.state, "ready", False)
        return {
            "status": "ok" if ready else "degraded",
            "artifacts_loaded": ready,
        }

    return app


# uvicorn entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
app = create_app()