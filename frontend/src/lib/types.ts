// Mirrors backend/app/models/schemas.py. Kept in sync by hand for now.

export interface HealthzResponse {
  status: "ok" | "degraded";
  artifacts_loaded: boolean;
}

export interface MovieSearchHit {
  title: string;
  score: number;
  id: number;
  year: number | null;
}

export interface RecommendationItem {
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
}

export interface RecommendDebug {
  rank_ms: number;
  enrich_ms: number;
  n_results: number;
  reason?: string;
}

export interface RecommendResponse {
  query: { title: string; id: number; index: number } | null;
  results: RecommendationItem[];
  debug: RecommendDebug | null;
}

export interface RecommendRequest {
  title: string;
  top_n?: number;
  genres?: string[];
  year_min?: number;
  year_max?: number;
  min_rating?: number;
  diversify?: boolean;
}

export interface FilterState {
  genres: string[];
  yearRange: [number, number];
  minRating: number;
  diversify: boolean;
}