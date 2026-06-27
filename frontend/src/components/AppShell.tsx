import { Link } from "react-router-dom";
import { Film } from "lucide-react";
import SearchBar from "@/components/SearchBar";
import { Separator } from "@/components/ui/separator";
import { Toaster } from "@/components/ui/sonner";
import { useHealthzPing } from "@/hooks/useHealthzPing";

interface AppShellProps {
  children: React.ReactNode;
}

// Page chrome: header w/ logo + search, main content, footer.
// The healthz ping fires on mount, so the first /recommend call doesn't
// hit Render's free-tier cold start.
export default function AppShell({ children }: AppShellProps) {
  useHealthzPing();

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur">
        <div className="container flex h-16 items-center gap-4">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <Film className="h-5 w-5" />
            <span>Movie Recommender</span>
          </Link>
          <div className="ml-auto flex flex-1 justify-end">
            <SearchBar />
          </div>
        </div>
      </header>

      <main className="container flex-1 py-6">{children}</main>

      <footer className="border-t">
        <div className="container flex h-14 items-center justify-between text-xs text-muted-foreground">
          <span>TMDB-5000 · hybrid TF-IDF + SBERT · v2</span>
          <Separator orientation="vertical" className="mx-2 h-4" />
          <span>Built with FastAPI + React</span>
        </div>
      </footer>

      <Toaster richColors closeButton position="bottom-right" />
    </div>
  );
}