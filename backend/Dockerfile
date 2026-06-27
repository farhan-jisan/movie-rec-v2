# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Movie Recommender v2 — backend image
# ---------------------------------------------------------------------------
# Stage 1: install Python deps + toolchain for compiling scipy/sklearn wheels
# Stage 2: copy raw CSVs, build artifacts (parquet + tfidf + sbert + faiss)
# Stage 3: copy app source, pre-load SBERT model so cold starts skip the
#          HuggingFace download, and run uvicorn.
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools needed for numpy/scipy/scikit-learn wheels (slim image lacks them).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: build artifacts from the raw TMDB CSVs
# ---------------------------------------------------------------------------
FROM deps AS builder

# CSVs live in app/data/raw at runtime, but during the image build we only
# need them transiently — the artifacts are what's actually shipped.
COPY app/data/raw ./app/data/raw
COPY scripts ./scripts

# build_artifacts.py expects to run from the backend/ root (so the
# package layout matches runtime).  --force rebuilds everything so the
# image always ships a fresh parquet + tfidf + sbert + faiss.
# PYTHONPATH=/app makes `app.recommender` importable regardless of cwd.
RUN PYTHONPATH=/app python scripts/build_artifacts.py --force

# Pre-load SBERT so the running container never hits the HuggingFace cache
# on first /recommend call.  The model is baked into the image layers.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# ---------------------------------------------------------------------------
# Stage 3: slim runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    NLTK_DATA=/app/.cache/nltk_data

# Slim image has no compilers, so we copy the fully-built site-packages from
# the deps stage instead of re-installing.  This also keeps the runtime image
# ~600MB smaller than a single-stage build with build-essentials retained.
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

WORKDIR /app

# Copy the artifacts that were baked in stage 2.
COPY --from=builder /app/app/data/artifacts ./app/data/artifacts
COPY --from=builder /app/app/data/raw ./app/data/raw

# Copy the application source.
COPY app ./app
COPY scripts ./scripts

# Ensure the SBERT cache from stage 2 is present (otherwise HF will redownload).
COPY --from=builder /root/.cache/huggingface /app/.cache/huggingface

# Render sets $PORT; default to 8000 for local docker runs.
EXPOSE 8000
ENV PORT=8000

# Single uvicorn worker — fastapi + the in-memory recommender is single-process
# by design.  --proxy-headers so X-Forwarded-* from Render reaches us.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]