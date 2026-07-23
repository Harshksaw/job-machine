import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds into the FastAPI service's static dir; Task 5 mounts it under `/`.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8420", changeOrigin: true },
      "/health": { target: "http://localhost:8420", changeOrigin: true },
    },
  },
});
