import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for Movie Recommender v2.
// - @/ alias -> src/
// - VITE_API_BASE is read by src/lib/api.ts at build time.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls in dev so the browser doesn't hit CORS.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
