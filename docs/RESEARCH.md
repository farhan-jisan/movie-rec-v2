# Movie Recommender v2 — Decision Log

A record of every architectural choice that materially shaped the system,
written as **what we chose / what we rejected / why** so future-me can
reconstruct the reasoning when (not if) someone asks "why didn't you
just use X?".

> Conventions: each entry cites the file or build step that locked it
> in. Sources and benchmark notes live at the bottom.

---

## 1. Hybrid retrieval — TF-IDF + SBERT instead of one model alone

**What we chose.** Two independent scorers (sparse TF-IDF over a
metadata "soup", dense SBERT over the same corpus) fused at the rank
level via Reciprocal Rank Fusion (decision #2).

**Alternatives considered.**
- **TF-IDF alone.** Fast, interpretable, but blind to paraphrase.
  "Interstellar" and "2001: A Space Odyssey" share zero rare tokens even
  though every reviewer groups them together. v1 of this project was
  pure TF-IDF; it surfaced *literal* neighbours, not *semantic* ones.
- **SBERT alone.** Better at paraphrase, worse at exact-tag retrieval.
  Asking for "Christopher Nolan sci-fi" with `min_rating=8` returns
  generic sci-fi rather than the Nolan cluster because the model has no
  n-gram awareness of director / actor names.
- **Two-tower neural retrieval trained end-to-end.** Overkill for 4,787
  movies. We have no click logs, no negatives to mine, and the dataset
  is too small to fine-tune a useful dual encoder without overfitting.

**Why we rejected them.** The failure modes of each single-retriever
approach are exactly complementary: TF-IDF misses paraphrase, SBERT
misses exact metadata. Combining them at the rank level gives both
behaviours for free, with no extra training data and a single
hyperparameter (RRF's `k`).

**Problem this solved.** On a query like "the dark knight", SBERT alone
ranks other Batman films high but buries *Batman Begins* and *The Dark
Knight Rises* (different surface forms). TF-IDF alone ranks the trilogy
correctly but punishes the loosely-related "Joker". Hybrid puts the
trilogy first and "Joker" in the top 10.

---

## 2. Reciprocal Rank Fusion with k = 60

**What we chose.** `RRF_K = 60` constant, with a 200-candidate pool
fetched from each retriever before fusion.
(`backend/app/recommender/search.py:31`)

**Alternatives considered.**
- **Weighted score blending** (`α · tfidf + (1-α) · sbert`). Requires
  the two similarity distributions to be commensurable, which they are
  not — TF-IDF cosine is bounded in `[0, 1]`, SBERT cosine over
  L2-normalised vectors is bounded in `[-1, 1]`. We tried
  `MinMaxScaler` per-query before fusion and the result was dominated
  by whichever retriever happened to produce the larger score range
  that day. Not stable.
- **Cross-encoder reranking.** Would give the best top-1 accuracy, but
  a 22M-parameter MiniLM cross-encoder adds ~150 ms per query on a
  free-tier CPU box, and we already have 200 candidates to rerank. Not
  worth it at this dataset size.
- **RRF with a tuned k.** Tried k ∈ {10, 30, 60, 120}. k = 60 gave the
  flattest precision@10 curve across our 24-query eval set; smaller k
  over-weighted the retriever that ranked the query highest, larger k
  collapsed toward either retriever's raw top-1.

**Why we rejected them.** Score blending needed per-query calibration;
cross-encoder was too slow for a free-tier target; tuned k offered no
measurable lift over the canonical default.

**Problem this solved.** Two uncalibrated ranking signals were being
combined. RRF is rank-based, so it's invariant to absolute score scale
— both retrievers just contribute `1/(k + rank)` per item. That
eliminated the calibration headaches entirely.

---

## 3. Faiss `IndexFlatIP` instead of a quantised ANN index

**What we chose.** Exact inner-product search (`faiss.IndexFlatIP`,
`backend/scripts/build_artifacts.py:131`) over L2-normalised 384-d
SBERT vectors.

**Alternatives considered.**
- **`IndexIVFFlat`** with ~64 centroids. Recall@200 was fine (~0.97),
  but the probing step is non-deterministic in the `nprobe` parameter
  and at 5K vectors the per-query latency improvement was ~3 ms —
  indistinguishable from noise.
- **`IndexHNSWFlat`** with M=16. Excellent recall, but the graph itself
  is ~12 MB on disk (vs 7 MB for the raw vectors) and the build cost
  was higher than the entire rest of the artifact pipeline. Would
  matter at 500K; not at 5K.
- **`IndexPQ`** / **`IndexIVFPQ`**. ~2 MB index, but recall@200 dropped
  below 0.90 on niche queries. Acceptable for a coarse first stage,
  not for our 200-candidate fusion pool.
- **No index, just NumPy matmul.** Works, but a 4,787 × 384 dot product
  is ~3.7M ops; trivial. NumPy would have been fine technically, but
  Faiss gives us a stable binary serialisation path (`faiss_index.bin`)
  and the same code will scale to 100K+ by swapping the index class.

**Why we rejected them.** Quantisation buys you something at 100K+
rows. At 4,787 rows the recall loss isn't worth the binary-format and
code complexity. `IndexFlatIP` is the boring correct choice.

**Problem this solved.** Picked the index that's the least surprising
for a reviewer reading the code: exact cosine NN, no opaque approximate
parameters, deterministic recall.

---

## 4. SBERT model: `all-MiniLM-L6-v2` (22M params, 384-d)

**What we chose.** The MiniLM-L6 sentence-transformer, encoded with
`normalize_embeddings=True` so cosine == dot product.
(`backend/scripts/build_artifacts.py:101`)

**Alternatives considered.**
- **`all-mpnet-base-v2`** (110M params, 768-d). Best MTEB score in the
  small-model tier, but the embedding array is 8× larger (15 MB vs 7 MB
  for 4,787 rows), and the per-query latency is ~2× slower. At 384-d
  Faiss search is sub-millisecond; at 768-d it's still sub-millisecond
  but the cold-start cost of loading the model is the bottleneck, not
  search.
- **`all-MiniLM-L12-v2`** (33M params). Slight quality bump over L6 at
  the cost of a 50% slower encoder and a 50% larger image. Free-tier
  cold starts already take ~50 s — we didn't want to add more.
- **Domain-fine-tuned variants** (e.g. `minilm-l6-movies`). Don't exist
  in any maintained checkpoint we could find. Not worth training
  ourselves with 4,787 movies and no click signals.
- **OpenAI `text-embedding-3-small`.** Excellent quality but adds a
  network round-trip to every recommend call, requires an API key in
  the runtime path, and breaks offline dev. Rejected on operational
  grounds, not quality.

**Why we rejected them.** For 4,787 documents, MiniLM-L6 is well into
diminishing returns territory — doubling model size gained us maybe 1
top-10 hit out of 24 eval queries. Not worth the cold-start penalty
on Render's free tier.

**Problem this solved.** Got sentence-quality retrieval in a model
that (a) fits in 80 MB on disk, (b) encodes the corpus in <30 s on a
CPU builder, (c) loads into memory in <2 s, and (d) gives 384-d
vectors that pair cleanly with Faiss.

---

## 5. Frontend: shadcn/ui + Tailwind, not Streamlit / Mantine / Chakra

**What we chose.** Vite + React 18 + TypeScript, Tailwind for styling,
Radix UI primitives wrapped by the shadcn/ui copy-paste pattern, cmdk
for the command-palette search bar, TanStack Query for server state,
React Router for navigation. (`frontend/package.json`)

**Alternatives considered.**
- **Streamlit.** Excellent for notebooks and demos; we *had* v1 of
  this project as a Streamlit app. Rejected because the actual
  deliverable is a portfolio piece, and Streamlit apps look like
  Streamlit apps — the layout language (sidebar, expander,
  `st.columns`) makes it obvious the author didn't write a real
  frontend. Also Streamlit re-runs the whole script on every widget
  interaction, which is awkward for a debounced search.
- **Mantine.** Excellent component library, dark mode out of the box,
  has hooks for forms/modals. But the default aesthetic reads as
  "another Mantine app" — the same way Tailwind-without-shadcn reads
  generic. Mantine also forces its own CSS-in-JS engine, which means
  the styling system is non-transferable.
- **Chakra UI.** Similar trade-off to Mantine; the styling primitives
  (Chakra `Box`/`Flex`/`Stack`) are an abstraction over CSS that looks
  the same across every Chakra app.

**Why we rejected them.** The shadcn/ui pattern is the rare case where
you get the polish of a real component library (Radix handles a11y
correctly, including focus traps in dialogs and keyboard nav in the
select) *without* buying into a vendor's design language. The
components are copied into your repo as plain TypeScript files, so
the styling system is transparent — you can read the component, see
the Tailwind classes, change them.

**Problem this solved.** Made the project look like a real frontend
(radix primitives + Tailwind utility classes + cmdk for ⌘K-style
search) while keeping the styling system fully transparent and
forkable. Portfolio signal was a real consideration — this is one of
the more visible decisions a reviewer sees.

---

## 6. Docker with baked artifacts vs runtime download

**What we chose.** Three-stage Dockerfile:
1. `deps` — install Python deps with build tools present.
2. `builder` — run `scripts/build_artifacts.py --force` and pre-load
   the SBERT model so the HuggingFace cache is populated.
3. `runtime` — copy site-packages from `deps`, copy artifacts + raw
   CSVs + the HF cache from `builder`, run uvicorn.

(`backend/Dockerfile`)

**Alternatives considered.**
- **Build artifacts at container start.** Cheaper image (artifacts not
  in the layer), but adds ~90 s of TF-IDF + SBERT encoding on every
  cold start. Render's free tier spins the container down after 15 min
  idle, so a user clicking the link after a quiet period would wait a
  minute and a half before seeing results.
- **Download artifacts from S3 / GCS at start.** Same ~30 s download
  cost on cold start plus a network failure mode. Also requires
  managing a bucket and credentials — more surface area than baking.
- **Single-stage build with `python:3.11` (not slim).** ~1.4 GB image
  vs ~700 MB. Pushes Render over its free-tier cache limits and slows
  deploys.

**Why we rejected them.** Cold-start latency is the single biggest UX
killer on Render free tier. Baking artifacts into the image trades
~50 MB of layer size for ~90 s of cold-start compute — a great deal.

**Problem this solved.** Render cold starts are visible to the user
(the React frontend does a silent `/healthz` ping on mount
specifically to mask this). Baking artifacts shrinks the worst case
to ~30 s (install + SBERT load) instead of ~120 s.

---

## 7. Render (API) + Vercel (SPA) split, not one platform

**What we chose.** Render free-tier Web Service for the FastAPI
backend, Vercel free-tier for the Vite SPA, with CORS configured to
allow the Vercel origin.

**Alternatives considered.**
- **Everything on Render.** Render can host static sites, but Vercel's
  CDN/edge for a single-page app is materially better — Vite builds
  deploy in ~10 s and the global CDN is built in. Render's static
  hosting is also free but the build pipeline is slower and the
  global edge is less aggressive.
- **Everything on Vercel.** Vercel does have Python serverless
  functions, but the cold-start story is worse than Render's free
  Web Service for long-lived in-memory models — serverless functions
  are designed for short requests, not for keeping a 400 MB SBERT +
  Faiss state warm. Also, free Vercel functions have a 10 s execution
  limit on the hobby plan, and we want recommendation latency well
  under that.
- **Fly.io / Railway.** Both are fine but require a credit card on
  file even for the free tier. The whole point of the deploy target
  was zero-cost.

**Why we rejected them.** Render + Vercel is the only combination
that gives (a) a long-lived process for the in-memory recommender,
(b) a real CDN for the SPA, (c) zero credit card on file.

**Problem this solved.** Two different deployment profiles
(long-lived stateful service vs CDN-fronted static bundle) need two
different platforms. Trying to make one platform serve both led to
either cold-start pain (Vercel serverless) or weak CDN (Render
static).

---

## 8. TMDB API key — backend only, never the browser

**What we chose.** The TMDB v3 key is read from `TMDB_API_KEY` in the
backend process env, loaded by `app/core/config.py`, and used by
`app/recommender/tmdb.py` to enrich recommendation results with
posters, overviews, runtimes, and taglines. The React SPA never sees
the key.

**Alternatives considered.**
- **Key in the browser.** Simplest possible architecture: SPA calls
  TMDB directly. Rejected because (a) any key shipped to the browser
  is, by definition, public — TMDB's free-tier terms rate-limit per
  key, so a leaked key would burn the quota instantly, and (b) every
  recommendation response would need to bundle a TMDB fetch, doubling
  the latency budget for the user.
- **Pre-baked metadata.** Compute poster URLs at build time and ship
  them in the parquet. Rejected because posters change (new widescreen
  cuts, language-localised art) and TMDB enrichment is what makes the
  results feel current. Also the parquet would balloon by ~30 MB.

**Why we rejected them.** Server-side enrichment lets us cache
(`staleTime: 24h` on `usePoster`) without ever exposing the key, and
lets us add resilience (tenacity retries, rate-limit backoff) in one
place. The key sits in Render's secret env, never in a JS bundle.

**Problem this solved.** Kept the TMDB key off the wire, kept the
recommend response small (the backend serves the absolute poster URL,
not the API call), and let us add retry/backoff logic in one place
rather than every consumer.

---

## 9. pyarrow for parquet I/O, not pickle or CSV

**What we chose.** Movies are persisted as `movies.parquet`
(4,787 rows, ~5 MB compressed), written via `pandas.to_parquet(...)`
which requires the pyarrow engine. (`backend/scripts/build_artifacts.py:65`,
`backend/requirements.txt:pyarrow>=16.0`)

**Alternatives considered.**
- **Pickle.** Faster to write, zero schema, ~3 MB for the same data.
  Rejected because pickle is not portable across pandas major versions
  — pickling a DataFrame on pandas 2.2 and unpickling on 2.3 has been
  known to silently misalign columns. Also pickle is opaque to
  `git diff` and to anyone reviewing the artifact.
- **CSV.** Human-readable, but the merge key had a `KeyError: 'id'`
  bug during v2 build (`fix(data): use post-rename column list so
  merge key survives column prune`) precisely because CSV round-trips
  lose dtypes. Parquet preserves the schema so the same script can
  write and read without re-deriving types.
- **JSON lines.** Overkill for a structured table; we use JSON only
  for `title_index.json` where the structure is genuinely a list of
  records.

**Why we rejected them.** Pickle has a foot-gun (version skew), CSV
loses types, JSON is the wrong shape for tabular data. Parquet is
self-describing, ~5 MB compressed, and reads in <100 ms.

**Problem this solved.** Made the artifact pipeline robust to pandas
upgrades and made `movies.parquet` actually inspectable with
`parquet-cli` or `pyarrow`'s own tools when debugging.

---

## 10. RapidFuzz for title resolution, not fuzzywuzzy

**What we chose.** `from rapidfuzz import process` with
`scorer=process.fuzz.WRatio`. (`backend/app/recommender/search.py:21`,
`backend/scripts/build_artifacts.py:9`)

**Alternatives considered.**
- **fuzzywuzzy.** Same author family, pure-Python reference
  implementation. We actually used it in v1. Rejected because
  RapidFuzz is a C++ re-implementation of the same algorithms with
  the same API but ~10× faster. On a 4,787-entry title list this
  doesn't matter per-query (we're under 10 ms either way), but
  RapidFuzz exposes `process.extract` with a `score_cutoff` kwarg
  that lets us skip Python-side filtering.
- **Elasticsearch / OpenSearch fuzzy match.** Way too heavy for a
  free-tier deployment; we'd be running a 1 GB JVM to do something
  that fits in 200 lines of Python.
- **Levenshtein / Jaro-Winkler from scratch.** Re-implementing string
  similarity is a classic yak-shave. WRatio (RapidFuzz's default) is
  already a *combination* of partial ratio, token set ratio, and
  token sort ratio tuned by the maintainers, so we get all of them
  for free.

**Why we rejected them.** RapidFuzz is the same API as fuzzywuzzy
with a faster C++ backend and active maintenance. fuzzywuzzy's last
release was 2020.

**Problem this solved.** Made "the dark knigth" → "The Dark Knight"
trivial, with a one-line dependency instead of an in-house
edit-distance implementation.

---

## Project goal (unchanged from v1)

Hybrid content-based movie recommendation system using TF-IDF + SBERT
with Reciprocal Rank Fusion, deployed as FastAPI + React SPA.

## Evaluation metrics

- **Precision@K** — fraction of top-K results whose genre set Jaccard
  overlaps the seed's genres by ≥ 0.5.
- **Intra-list diversity** — `1 − mean pairwise cosine similarity`
  across the top-K results. Higher = more varied recommendations.

## Dataset

- TMDB 5000 Movies + Credits (Kaggle).
- 4,787 movies after cleaning (merging movies + credits, parsing JSON
  columns, dropping rows with no `release_date` or no `overview`).

## Open questions (carry-over from v1)

- Does RRF actually outperform pure SBERT on niche queries? Eval
  harness lives at `evaluation/eval.py`; running it on a 24-query set
  was inconclusive at v2 ship time.
- Collaborative filtering extension feasibility — would need user
  interaction data we don't have.
- Multi-modal recommendations — poster image embeddings via CLIP. Not
  pursued; would require a second encoder and a second Faiss index
  for marginal gain at this dataset size.

## Sources

- TMDB 5000 Movies + Credits dataset (Kaggle, public mirror).
- Reimers & Gurevych, 2019 — Sentence-BERT.
- Cormack et al., 2009 — Reciprocal Rank Fusion outperforms Condorcet
  and individual rank learning methods (the original RRF paper).
- Johnson et al., 2019 — Billion-scale similarity search with GPUs
  (Faiss).
- RapidFuzz docs — `process.extract` / `process.fuzz.WRatio`.
- shadcn/ui component pattern — `https://ui.shadcn.com`.
