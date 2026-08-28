import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The PWA talks to the FastAPI service. In dev that is the local uvicorn; in
// production the app is served by Cloud Run alongside the API, so the same
// relative /api paths work untouched.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.GALLA_API ?? "http://localhost:8080" },
      "/ingest": { target: process.env.GALLA_API ?? "http://localhost:8080" },
    },
  },
  build: { outDir: "dist" },
});
