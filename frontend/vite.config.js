import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The PWA talks to the FastAPI service. In dev that is the local uvicorn; in
// production the app is served by Cloud Run alongside the API, so the same
// relative /api paths work untouched.
// A new build id on every build is what invalidates the service worker cache.
const BUILD_ID = Date.now().toString(36);

export default defineConfig({
  define: { "import.meta.env.VITE_BUILD_ID": JSON.stringify(BUILD_ID) },
  plugins: [
    react(),
    {
      // Stamp the same id into the worker itself, so its bytes change too.
      name: "galla-build-id",
      writeBundle(options) {
        const worker = path.join(options.dir ?? "dist", "sw.js");
        if (!fs.existsSync(worker)) return;
        fs.writeFileSync(
          worker,
          fs.readFileSync(worker, "utf8").replace("__BUILD_ID__", BUILD_ID));
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.GALLA_API ?? "http://localhost:8080" },
      "/ingest": { target: process.env.GALLA_API ?? "http://localhost:8080" },
    },
  },
  build: { outDir: "dist" },
});
