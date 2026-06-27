import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { RecommendationItem } from "@/lib/types";

interface MovieCardProps {
  movie: RecommendationItem;
}

// Single movie card: poster, title, year, rating badge, hover synopsis.
// Clicking anywhere navigates to /movie/:id.
export default function MovieCard({ movie }: MovieCardProps) {
  const hasPoster = !!movie.poster_url;

  return (
    <Link to={`/movie/${movie.id}`} className="group">
      <Card className="h-full overflow-hidden transition-shadow group-hover:shadow-md">
        <div className="relative aspect-[2/3] w-full overflow-hidden bg-muted">
          {hasPoster ? (
            <img
              src={movie.poster_url!}
              alt={`${movie.title} poster`}
              loading="lazy"
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
          ) : (
            <Skeleton className="h-full w-full" />
          )}
          <div className="absolute right-2 top-2">
            <Badge variant="secondary" className="font-mono">
              ★ {movie.vote_average.toFixed(1)}
            </Badge>
          </div>
        </div>
        <CardContent className="space-y-1 p-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="line-clamp-2 text-sm font-semibold leading-tight">
              {movie.title}
            </h3>
            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {movie.year || "—"}
            </span>
          </div>
          {movie.reason_tags.length > 0 && (
            <p className="line-clamp-2 text-[11px] text-muted-foreground">
              {movie.reason_tags[0]}
            </p>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}