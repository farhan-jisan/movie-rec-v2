import MovieCard from "./MovieCard";
import type { RecommendationItem } from "@/lib/types";

interface MovieGridProps {
  movies: RecommendationItem[];
}

// Responsive grid of MovieCards. 1 col mobile -> 6 col wide desktop.
export default function MovieGrid({ movies }: MovieGridProps) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {movies.map((m) => (
        <MovieCard key={m.id} movie={m} />
      ))}
    </div>
  );
}