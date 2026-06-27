import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Fetch the absolute TMDB poster URL for a given movie id.
export function usePoster(
  movieId: number | null | undefined,
  width: "w500" | "w780" | "original" = "w500",
) {
  return useQuery({
    queryKey: ["poster", movieId, width],
    queryFn: async (): Promise<string | null> => {
      if (movieId == null) return null;
      const res = await api.getPoster(movieId, width);
      return res.poster_url;
    },
    enabled: movieId != null,
    staleTime: 24 * 60 * 60_000, // posters rarely change
  });
}