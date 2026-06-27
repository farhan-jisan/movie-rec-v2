import { useEffect } from "react";
import { api } from "@/lib/api";

// Silent cold-start warmer. Pings /api/v1/healthz once when the component
// using this hook mounts. Render free tier spins down after 15 min idle and
// takes ~1 min to wake up — this pre-warms it so the user's first real
// /recommend call doesn't hit the cold-start penalty.
//
// Failures are swallowed silently. No UI feedback is shown.
export function useHealthzPing(): void {
  useEffect(() => {
    let cancelled = false;
    api
      .healthz()
      .catch(() => {
        // Swallow. The healthz endpoint is best-effort.
      })
      .finally(() => {
        cancelled = cancelled;
      });
    return () => {
      cancelled = true;
    };
  }, []);
}