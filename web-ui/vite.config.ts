import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Vite builds the SPA into the Python package so `era5 ui` can serve it.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8788",
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../src/era5_etl/web/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    // Plotly alone is ~4.6 MB minified and ships as a single chunk; the
    // main bundle is around 2.5 MB. Splitting them further would require
    // dynamic imports throughout the SPA. Bumping the warning ceiling
    // makes the build log meaningful again — anything beyond 5 MB IS
    // worth investigating.
    chunkSizeWarningLimit: 5_000,
    rollupOptions: {
      output: {
        manualChunks: {
          // Isolate the largest dependencies in their own chunks so the
          // main entry stays small and warm-cache reloads are quick.
          plotly: ["plotly.js-dist-min", "react-plotly.js"],
          deckgl: [
            "@deck.gl/core",
            "@deck.gl/extensions",
            "@deck.gl/layers",
            "@deck.gl/react",
            "deck.gl",
          ],
          maplibre: ["maplibre-gl", "react-map-gl"],
          monaco: ["@monaco-editor/react"],
        },
      },
    },
  },
});
