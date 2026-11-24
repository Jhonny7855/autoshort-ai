import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves project sites from /<repo>/, so the base path comes from
// VITE_BASE (set in CI). Local dev and the bundled backend use "/".
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
    base: env.VITE_BASE || "/",
    plugins: [react()],
    server: {
      port: 5273,
      strictPort: true,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8787",
          changeOrigin: true,
          ws: true,
        },
        "/media": {
          target: "http://127.0.0.1:8787",
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
    },
  };
});
