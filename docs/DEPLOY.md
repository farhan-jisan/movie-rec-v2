# Deploy guide — Movie Recommender v2

Two free-tier services. Total cost: **$0**.

```
GitHub repo (movie-rec-v2/)
        │
        ├──► Render (mr-api)        https://mr-api.onrender.com
        │     - Python 3.11-slim
        │     - Dockerfile bakes artifacts + SBERT
        │     - Health check: /api/v1/healthz
        │
        └──► Vercel (mr-web)        https://mr-rec.vercel.app
              - Vite SPA
              - /api/* proxied via VITE_API_BASE
```

---

## Prereqs

- GitHub account with a new repo (e.g. `movie-rec-v2`).
- Render account (https://render.com — sign in with GitHub).
- Vercel account (https://vercel.com — sign in with GitHub).
- TMDB v3 API key from https://www.themoviedb.org/settings/api.

---

## 1. Push to GitHub

The repo is already committed locally (see `git log`). Add your remote and push:

```bash
cd movie-rec-v2
git remote add origin git@github.com:<you>/movie-rec-v2.git
git push -u origin main
```

> If you prefer HTTPS: `git remote add origin https://github.com/<you>/movie-rec-v2.git`.

---

## 2. Backend → Render

1. **Dashboard → New + → Blueprint**.
2. Connect the `movie-rec-v2` repo. Render auto-detects `render.yaml`.
3. Click **Apply**. Render provisions the `mr-api` service.
4. **Environment tab** → add the secret:
   - `TMDB_API_KEY` = your key (set as **Secret**, not visible).
5. Edit `ALLOWED_ORIGINS` to include your Vercel domain (you'll know it
   after step 3 — placeholder in `render.yaml` reads
   `https://<your-vercel-domain>.vercel.app`).
6. Click **Manual Deploy → Deploy latest commit**.
7. **First build** takes 3–5 minutes: it installs deps, runs
   `build_artifacts.py --force` (writes 6 artifacts), and pre-loads
   SBERT (~90MB download).
8. Verify:
   ```bash
   curl https://mr-api.onrender.com/api/v1/healthz
   # {"status":"ok","artifacts_loaded":true,...}
   ```

### Troubleshooting

- **Build fails at `build_artifacts.py`** — check Render logs. The CSVs
  ship in `backend/app/data/raw/`; if you moved them, update the
  Dockerfile's `COPY` line.
- **`/healthz` returns 503 with `artifacts_loaded: false`** — the image
  baked the artifacts in `app/data/artifacts/`, but your
  `ARTIFACTS_DIR` env var points somewhere else. Unset it (or set it to
  `/app/app/data/artifacts`).
- **TMDB posters all 404** — `TMDB_API_KEY` not picked up. Verify in
  the Render dashboard's **Environment** tab.

---

## 3. Frontend → Vercel

1. **Add New… → Project** → import the same `movie-rec-v2` repo.
2. **Root Directory** → click **Edit** → set to `frontend`.
3. Vercel auto-detects Vite and uses `vercel.json`.
4. **Environment Variables**:
   - `VITE_API_BASE` = `https://mr-api.onrender.com/api/v1`
     *(use the URL from step 2)*
5. Click **Deploy**. First build ~30s.
6. Visit `https://<your-project>.vercel.app`.

### Verify SPA routing

- `/` should show the search bar.
- `/movie/27205` (deep link) should also load — that's the
  `vercel.json` rewrite kicking in.

---

## 4. Wire CORS

Once you know your Vercel URL, go back to Render:

1. `mr-api` → **Environment** → edit `ALLOWED_ORIGINS` →
   `https://<your-project>.vercel.app`
2. Save → Render redeploys automatically.

---

## 5. End-to-end verification

```bash
API=https://mr-api.onrender.com
WEB=https://<your-project>.vercel.app

# 1. healthz
curl -fsS "$API/api/v1/healthz"

# 2. CORS preflight from Vercel origin
curl -i -X OPTIONS "$API/api/v1/recommend" \
  -H "Origin: $WEB" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"

# 3. real recommend call
curl -fsS -X POST "$API/api/v1/recommend" \
  -H "Content-Type: application/json" \
  -d '{"title":"The Dark Knight","top_k":5,"genres":[],"year_min":1900,"year_max":2026,"min_rating":0,"diversify":false}'
```

Open the Vercel URL in a browser, search **Avatar**, confirm posters
appear. If the first request takes ~30s, that's the Render free-tier
spin-down waking up — the React `AppShell` fires a silent `/healthz`
ping on mount to mask it on subsequent visits within the idle window.

---

## 6. Custom domains (optional)

### Render
- `mr-api` → **Settings → Custom Domain** → `api.yourdomain.com`.
- Add a CNAME record at your DNS: `api` → `mr-api.onrender.com`.

### Vercel
- Project → **Settings → Domains** → `yourdomain.com`.
- Update `ALLOWED_ORIGINS` in Render to include the new domain.

---

## 7. Continuous deploy

Both services auto-deploy on push to `main`. To disable Render
auto-deploy, edit `render.yaml` → `autoDeploy: false` and trigger
deploys manually from the dashboard.

---

## Cost summary

| Service  | Plan         | Limits                                                  | Cost  |
|----------|--------------|---------------------------------------------------------|-------|
| Render   | Free Web     | Spins down after 15 min idle; 750h/month                | $0    |
| Vercel   | Hobby        | 100 GB bandwidth/month, unlimited deploys               | $0    |
| TMDB     | Free         | 50 requests/sec                                         | $0    |
| **Total**|              |                                                         | **$0**|

The first cold start after Render idles out is ~30s. The subsequent
calls are sub-second (RRF over 4,800 movies runs in <100ms in-memory).