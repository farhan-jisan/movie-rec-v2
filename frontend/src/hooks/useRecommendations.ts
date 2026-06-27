import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { RecommendRequest, RecommendResponse } from "@/lib/types";

// Recommendations via POST /recommend.
// Disabled when title is empty. Filters pass straight through.
export function useRecommendations(
  payload: RecommendRequest | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ["recommend", payload],
    queryFn: async (): Promise<RecommendResponse> => {
      if (!payload) throw new Error("Missing payload");
      return api.recommend(payload);
    },
    enabled: enabled && !!payload && payload.title.trim().length > 0,
    staleTime: 5 * 60_000,
  });
}