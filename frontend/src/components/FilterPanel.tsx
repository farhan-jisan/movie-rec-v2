import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { FilterState } from "@/lib/types";

// Common TMDB genres — kept inline so we don't need a separate endpoint.
const GENRES = [
  "Action", "Adventure", "Animation", "Comedy", "Crime",
  "Documentary", "Drama", "Family", "Fantasy", "History",
  "Horror", "Music", "Mystery", "Romance", "Science Fiction",
  "TV Movie", "Thriller", "War", "Western",
];

const CURRENT_YEAR = new Date().getFullYear();

interface FilterPanelProps {
  state: FilterState;
  onChange: (next: FilterState) => void;
  className?: string;
}

export default function FilterPanel({ state, onChange, className }: FilterPanelProps) {
  const toggleGenre = (g: string) => {
    const has = state.genres.includes(g);
    onChange({
      ...state,
      genres: has ? state.genres.filter((x) => x !== g) : [...state.genres, g],
    });
  };

  return (
    <div className={cn("flex flex-col gap-6", className)}>
      {/* Year range */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">Year</label>
          <span className="text-xs text-muted-foreground tabular-nums">
            {state.yearRange[0]} – {state.yearRange[1]}
          </span>
        </div>
        <Slider
          min={1900}
          max={CURRENT_YEAR}
          step={1}
          value={state.yearRange}
          onValueChange={(v) =>
            onChange({ ...state, yearRange: [v[0], v[1]] as [number, number] })
          }
        />
      </div>

      {/* Min rating */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium">Min rating</label>
          <span className="text-xs text-muted-foreground tabular-nums">
            {state.minRating.toFixed(1)}
          </span>
        </div>
        <Slider
          min={0}
          max={10}
          step={0.1}
          value={[state.minRating]}
          onValueChange={(v) => onChange({ ...state, minRating: v[0] })}
        />
      </div>

      {/* Genre multi-select (toggle badges) */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Genres</label>
        <div className="flex flex-wrap gap-1.5">
          {GENRES.map((g) => {
            const active = state.genres.includes(g);
            return (
              <button
                type="button"
                key={g}
                onClick={() => toggleGenre(g)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-input bg-background hover:bg-accent hover:text-accent-foreground"
                )}
              >
                {g}
              </button>
            );
          })}
        </div>
        {state.genres.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {state.genres.map((g) => (
              <Badge key={g} variant="secondary" className="text-[10px]">
                {g}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Diversify toggle */}
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={state.diversify}
          onChange={(e) => onChange({ ...state, diversify: e.target.checked })}
          className="h-4 w-4 rounded border-input text-primary focus:ring-2 focus:ring-ring"
        />
        Diversify results
      </label>
    </div>
  );
}