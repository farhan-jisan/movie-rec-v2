# Movie Recommender v2

A content-based movie recommendation engine over the TMDB-5000 dataset,
served by a FastAPI backend and a React + Vite + shadcn/ui frontend.
Hybrid retrieval: **TF-IDF over a metadata "soup"** and **SBERT semantic
embeddings**, fused with **Reciprocal Rank Fusion** (k = 60).
Posters and metadata hydrate on demand from TMDB v3.

> v1 lived in a single notebook. v2 splits frontend / backend, adds
> semantic search, live TMDB enrichment, free-tier deploys on
> **Render** (API) and **Vercel** (SPA), and an evaluation harness
> with Precision@K and intra-list diversity.

---

## Architecture

```
┌────────────────────────┐         HTTPS         ┌──────────────────────────┐
│  React + Vite SPA      │ ────────────────────▶ │  FastAPI backend         │
│  (Vercel, free tier)   │   /api/v1/recommend    │  (Render, free tier)     │
│                        │                        │                          │
│  - shadcn/ui           │                        │  - pydantic v2 schemas   │
│  - TanStack Query      │                        │  - lifespan-loaded       │
│  - cmdk search         │                        │    recommender           │
│  - silent /healthz     │                        │  - TF-IDF + SBERT + RRF  │
│    ping on mount       │                        │  - TMDB v3 enrichment    │
└────────────────────────┘                        └──────────────────────────┘
                                                          │
                                                          ▼
                                                ┌──────────────────────────┐
                                                │  Artifacts (baked into   │
                                                │  Docker image at build)  │
                                                │                          │
                                                │  movies.parquet          │
                                                │  tfidf_vectorizer.joblib │
                                                │  tfidf_matrix.npz        │
                                                │  sbert_embeddings.npy    │
                                                │  faiss_index.bin         │
                                                │  title_index.json        │
                                                └──────────────────────────┘
```

### Ranking pipeline

1. **Fuzzy resolve** the query title against `title_index.json` (RapidFuzz
   `WRatio`, cutoff = 60).
2. **TF-IDF candidate generation** — sparse linear kernel between the
   query "soup" and the pre-computed `tfidf_matrix.npz`.  Vectorizer:
   `ngram_range=(1,2)`, `min_df=2`, `max_df=0.85`, `sublinear_tf=True`,
   `norm='l2'`, English stop-words.
3. **SBERT candidate generation** — top-K nearest neighbours in
   `faiss IndexFlatIP` over L2-normalised MiniLM-L6-v2 embeddings.
4. **Reciprocal Rank Fusion** — both ranked lists merged with k = 60
   over a 200-candidate pool.
5. **Post-filters** — year range, min rating, multi-genre (AND-combined),
   optional MMR-style diversification.
6. **TMDB hydration** (optional) — posters, overviews, runtime, taglines
   fetched in parallel via `ThreadPoolExecutor` with tenacity retries.

---

## Project layout

```
movie-rec-v2/
├── backend/                FastAPI service
│   ├── app/
│   │   ├── api/            routers (movies, recommend)
│   │   ├── core/           config + lifespan
│   │   ├── models/         pydantic schemas
│   │   └── recommender/    data, search, tmdb client
│   ├── scripts/            build_artifacts.py
│   ├── tests/              pytest suite
│   ├── Dockerfile          3-stage build, bakes artifacts + SBERT
│   ├── requirements.txt
│   └── .env.example
├── evaluation/             eval.py + queries.json
├── frontend/               Vite + React + shadcn/ui SPA
│   ├── src/
│   │   ├── components/     AppShell, SearchBar, FilterPanel, MovieCard…
│   │   ├── hooks/          useMovieSearch, useRecommendations…
│   │   ├── lib/            api.ts, types.ts, utils.ts
│   │   └── pages/          Home, MovieDetail
│   ├── vercel.json         SPA rewrite
│   └── package.json
├── scripts/                dev.sh, deploy-check.sh
├── render.yaml             Render Blueprint (mr-api service)
└── README.md
```

---

## Quickstart (local dev)

Requirements: Python 3.11+, Node 20+, a TMDB v3 API key
([free](https://www.themoviedb.org/settings/api)).

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # paste TMDB_API_KEY
python scripts/build_artifacts.py --force                 # ~2 min, writes 6 artifacts
uvicorn app.main:app --reload --port 8000

# 2. Frontend (in another terminal)
cd frontend
npm install
npm run dev                                               # http://localhost:5173
```

Or use the combined launcher:

```bash
./scripts/dev.sh
```

The Vite dev server proxies `/api/*` → `http://localhost:8000`, so the
SPA works out of the box with no `VITE_API_BASE` configured.

---

## Deploy (free)

### 1. Backend → Render

The Dockerfile bakes artifacts + the SBERT model at image build time, so
the running container only pays the FastAPI import cost on cold start.

1. Push this repo to GitHub.
2. In Render → **New → Blueprint**, point at the repo. Render reads
   `render.yaml` and provisions `mr-api`.
3. In the service's **Environment** tab, set `TMDB_API_KEY` as a secret.
4. Update `ALLOWED_ORIGINS` to include your Vercel domain.
5. Wait for the first deploy (~3–5 min: SBERT download + tfidf build).
6. Hit `https://mr-api.onrender.com/api/v1/healthz` — expect
   `{"status":"ok","artifacts_loaded":true}`.

### 2. Frontend → Vercel

1. In Vercel → **Add New → Project**, import the same repo.
2. **Root Directory** = `frontend`.
3. **Environment Variable**: `VITE_API_BASE` =
   `https://mr-api.onrender.com/api/v1`.
4. Deploy. `vercel.json` rewrites all routes to `/index.html` so deep
   links like `/movie/27205` work on refresh.

### 3. Verify

```bash
curl https://mr-api.onrender.com/api/v1/healthz
curl -X POST https://mr-api.onrender.com/api/v1/recommend \
  -H "Content-Type: application/json" \
  -d '{"title":"The Dark Knight","top_k":5,"genres":[],"year_min":1900,"year_max":2026,"min_rating":0,"diversify":false}'
```

Open the Vercel URL, search a movie, confirm posters load.  The first
request after a Render idle spin-down may take ~30s — subsequent calls
are sub-second.

---

## Environment variables

| Service  | Variable           | Required | Example                                                |
|----------|--------------------|----------|--------------------------------------------------------|
| backend  | `TMDB_API_KEY`     | yes      | `c1b2…`                                                |
| backend  | `ALLOWED_ORIGINS`  | yes      | `https://movie-rec.vercel.app`                         |
| backend  | `ARTIFACTS_DIR`    | no       | `/app/data/artifacts` (default = `<repo>/app/data/artifacts`) |
| frontend | `VITE_API_BASE`    | prod yes | `https://mr-api.onrender.com/api/v1`                   |

---

## Evaluation

```bash
cd backend
python -m evaluation.eval --top-k 10 --ground-truth genre --output eval.csv
```

Two metrics, both aggregated over `evaluation/queries.json`:

- **Precision@K** — share of top-K recommendations whose genre-Jaccard
  with the seed movie's genres is ≥ 0.5.
- **Intra-list diversity** — `1 − mean(pairwise_cosine(recommended_embeddings))`.

`--ground-truth tmdb` falls back to `--ground-truth genre` if the TMDB
API key isn't reachable from the evaluation host.

---

## License

MIT.  Dataset © TMDB, used under their terms of use.