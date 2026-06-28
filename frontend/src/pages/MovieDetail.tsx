import { Link, useParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import MovieGrid from "@/components/MovieGrid";
import { usePoster } from "@/hooks/usePoster";
import { useRecommendations } from "@/hooks/useRecommendations";

// Movie detail page. The :id param is the TMDB id of the clicked movie.
// We seed a recommendation request with the movie's title (looked up
// locally if present, otherwise fall back to whatever the user picked).
export default function MovieDetail() {
  const { id } = useParams<{ id: string }>();
  const movieId = Number(id);

  // The detail page pulls the poster directly from /movies/{id}/poster,
  // and fires a recommendation request using the *original* title as the
  // seed. We get the title from a module-level cache the search/MovieCard
  // populates (window.__mrCache), or by ID lookup via the recommendation
  // request's "search" resolution path.
  const [seedTitle, setSeedTitle] = useState<string | null>(null);

  useEffect(() => {
    const cached = (window as unknown as { __mrCache?: Map<number, string> })
      .__mrCache;
    if (cached && Number.isFinite(movieId)) {
      const t = cached.get(movieId);
      if (t) setSeedTitle(t);
    }
  }, [movieId]);

  const { data: poster, isFetching: posterLoading } = usePoster(
    Number.isFinite(movieId) ? movieId : null
  );

  const { data: recs, isFetching: recsLoading } = useRecommendations(
    seedTitle
      ? {
          title: seedTitle,
          top_n: 12,
          genres: [],
          year_min: 1900,
          year_max: new Date().getFullYear(),
          min_rating: 0,
          diversify: false,
        }
      : null
  );

  return (
    <div className="space-y-6">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Link>
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-[300px_1fr]">
        <div>
          {posterLoading && <Skeleton className="aspect-[2/3] w-full" />}
          {!posterLoading && poster && (
            <img
              src={poster}
              alt={`Movie ${movieId} poster`}
              className="w-full rounded-lg border shadow-sm"
            />
          )}
          {!posterLoading && !poster && (
            <Skeleton className="aspect-[2/3] w-full" />
          )}
        </div>

        <div className="space-y-3">
          <h1 className="text-2xl font-semibold">
            {seedTitle ?? `Movie #${movieId}`}
          </h1>
          {!seedTitle && (
            <p className="text-sm text-muted-foreground">
              Detail metadata isn&rsquo;t loaded for this id yet. Showing
              recommendations is disabled.
            </p>
          )}
          {recs && recs.results.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {recs.query?.title && (
                <Badge variant="outline">{recs.query.title}</Badge>
              )}
            </div>
          )}
        </div>
      </div>

      {seedTitle && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">You might also like</h2>
          {recsLoading && (
            <Skeleton className="h-64 w-full" />
          )}
          {recs && recs.results.length > 0 && (
            <MovieGrid movies={recs.results} />
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">About</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This view will hydrate with the full overview, cast, and crew once the
          backend&rsquo;s <code>/movies/{movieId}</code> endpoint is exposed.
        </CardContent>
      </Card>
    </div>
  );
}