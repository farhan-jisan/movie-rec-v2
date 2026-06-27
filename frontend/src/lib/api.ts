// Thin typed fetch wrapper around the FastAPI backend.
// In dev: VITE_API_BASE is empty, so requests go through the Vite proxy at /api/*.
// In prod: VITE_API_BASE is set to the Render URL (e.g. https://mr-api.onrender.com).

const RAW_BASE = import.meta.env.VITE_API_BASE ?? "";
const API_BASE = RAW_BASE.replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  const text = await res.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? res.statusText;
    throw new ApiError(`HTTP ${res.status}: ${detail}`, res.status, body);
  }
  return body as T;
}

// ---------- Endpoints ------------------------------------------------------ //

export const api = {
  healthz: () => request<{ status: string; artifacts_loaded: boolean }>(
    "/api/v1/healthz"
  ),

  searchMovies: (q: string, limit = 8) =>
    request<{
      query: string;
      results: Array<{ title: string; score: number; id: number; year: number | null }>;
    }>(`/api/v1/movies/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  getPoster: (movieId: number, width: "w500" | "w780" | "original" = "w500") =>
    request<{ movie_id: number; poster_url: string | null; width: string }>(
      `/api/v1/movies/${movieId}/poster?width=${width}`
    ),

  recommend: (body: {
    title: string;
    top_n?: number;
    genres?: string[];
    year_min?: number;
    year_max?: number;
    min_rating?: number;
  }) =>
    request<{
      query: { title: string; id: number; index: number } | null;
      results: Array<{
        index: number;
        id: number;
        title: string;
        year: number;
        vote_average: number;
        score: number;
        tfidf_rank: number | null;
        sbert_rank: number | null;
        reason_tags: string[];
        poster_url: string | null;
        overview: string | null;
        runtime: number | null;
        tagline: string | null;
      }>;
      debug: { rank_ms: number; enrich_ms: number; n_results: number } | null;
    }>("/api/v1/recommend", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};