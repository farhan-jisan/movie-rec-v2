import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import FilterPanel from "@/components/FilterPanel";
import MovieGrid from "@/components/MovieGrid";
import SearchBar from "@/components/SearchBar";
import { useRecommendations } from "@/hooks/useRecommendations";
import type { FilterState, RecommendRequest } from "@/lib/types";

const DEFAULT_FILTERS: FilterState = {
  yearRange: [1900, new Date().getFullYear()],
  minRating: 0,
  genres: [],
  diversify: false,
};

// Top-level landing page. Reads ?q= to auto-trigger a recommendation.
// Form state (title + filters) is local; the request payload is built on submit.
export default function Home() {
  const [params, setParams] = useSearchParams();
  const initialTitle = params.get("q") ?? "";
  const [title, setTitle] = useState(initialTitle);
  const [submittedTitle, setSubmittedTitle] = useState(initialTitle);
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);

  // When ?q= changes (e.g., SearchBar -> navigate("/?q=...")), keep state in sync.
  useEffect(() => {
    const q = params.get("q") ?? "";
    setTitle(q);
    setSubmittedTitle(q);
  }, [params]);

  const request: RecommendRequest = useMemo(
    () => ({
      title: submittedTitle,
      top_n: 12,
      genres: filters.genres,
      year_min: filters.yearRange[0],
      year_max: filters.yearRange[1],
      min_rating: filters.minRating,
      diversify: filters.diversify,
    }),
    [submittedTitle, filters]
  );

  const { data, isFetching, isError, error } = useRecommendations(
    submittedTitle ? request : null
  );

  const onSubmit = () => {
    const t = title.trim();
    if (!t) return;
    setSubmittedTitle(t);
    setParams({ q: t }, { replace: true });
  };

  return (
    <div className="grid gap-6 md:grid-cols-[280px_1fr]">
      {/* Left: filters */}
      <aside className="space-y-4">
        <Card>
          <CardContent className="p-4">
            <h2 className="mb-3 text-sm font-semibold">Find similar movies</h2>
            <SearchBar />
            <div className="mt-4">
              <FilterPanel state={filters} onChange={setFilters} />
            </div>
            <Button
              onClick={onSubmit}
              disabled={!title.trim()}
              className="mt-4 w-full"
            >
              Recommend
            </Button>
          </CardContent>
        </Card>
      </aside>

      {/* Right: results */}
      <section>
        {!submittedTitle && (
          <EmptyState />
        )}

        {submittedTitle && isFetching && (
          <SkeletonGrid />
        )}

        {submittedTitle && isError && (
          <Card>
            <CardContent className="p-6 text-sm text-destructive">
              {(error as Error)?.message ?? "Failed to fetch recommendations."}
            </CardContent>
          </Card>
        )}

        {submittedTitle && !isFetching && !isError && data && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Top {data.results.length} picks for{" "}
              <span className="font-medium text-foreground">{data.query.title}</span>
              <span className="ml-2 text-xs">
                · {((data.debug.rank_ms ?? 0) + (data.debug.enrich_ms ?? 0)).toFixed(0)} ms
              </span>
            </p>
            {data.results.length === 0 ? (
              <Card>
                <CardContent className="p-6 text-sm text-muted-foreground">
                  No results passed your filters — try relaxing them.
                </CardContent>
              </Card>
            ) : (
              <MovieGrid movies={data.results} />
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center gap-2 p-12 text-center">
        <h2 className="text-lg font-semibold">Pick a movie to get started</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          Type a title above. We&rsquo;ll fuzzy-match it, then hybrid-rank the
          catalog with TF-IDF and SBERT, fused with Reciprocal Rank Fusion.
        </p>
      </CardContent>
    </Card>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {Array.from({ length: 12 }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="aspect-[2/3] w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}