import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useMovieSearch } from "@/hooks/useMovieSearch";

// Debounced fuzzy title search with a "press Enter to recommend" affordance.
// Uses shadcn Command + cmdk for keyboard navigation.
export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const navigate = useNavigate();

  // 200ms debounce keeps /movies/search calls light without feeling laggy.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const { data: hits = [], isFetching } = useMovieSearch(debounced, 8);

  const open = useMemo(() => debounced.length > 0, [debounced]);

  const onSubmit = (title: string) => {
    if (!title) return;
    // Jump to Home with the title preselected (Home reads ?q=).
    navigate(`/?q=${encodeURIComponent(title)}`);
  };

  return (
    <div className="relative w-full max-w-xl">
      <Command shouldFilter={false} className="rounded-lg border shadow-sm">
        <CommandInput
          value={query}
          onValueChange={setQuery}
          placeholder="Search a movie title…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && query.trim()) {
              onSubmit(query.trim());
            }
          }}
        />
        {open && (
          <CommandList>
            {isFetching && (
              <div className="p-3 text-xs text-muted-foreground">Searching…</div>
            )}
            {!isFetching && hits.length === 0 && (
              <CommandEmpty>No matches. Press Enter to try anyway.</CommandEmpty>
            )}
            {hits.length > 0 && (
              <CommandGroup heading="Matches">
                {hits.map((h) => (
                  <CommandItem
                    key={`${h.id}-${h.title}`}
                    value={`${h.title} ${h.year ?? ""}`}
                    onSelect={() => onSubmit(h.title)}
                  >
                    <span className="flex-1 truncate">{h.title}</span>
                    {h.year != null && (
                      <span className="ml-2 text-xs text-muted-foreground">{h.year}</span>
                    )}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {Math.round(h.score)}%
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        )}
      </Command>
    </div>
  );
}