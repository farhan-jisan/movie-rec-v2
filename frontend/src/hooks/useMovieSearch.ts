import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MovieSearchHit } from "@/lib/types";

// Fuzzy movie title search via /movies/search?q=...
// Returns the response on success or null when q is empty.
export function useMovieSearch(query: string, limit = 8) {
  return useQuery({
    queryKey: ["movies", "search", query, limit],
    queryFn: async (): Promise<MovieSearchHit[]> => {
      if (!query || query.trim().length === 0) return [];
      const res = await api.searchMovies(query, limit);
      return res.results;
    },
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  });
}