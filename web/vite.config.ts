import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Dev: Vite on :5173 proxies /api to the FastAPI engine on :8765.
// Build: dist/ is served by FastAPI itself (one origin, no CORS).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
