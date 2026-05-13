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
  },
});
