import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发时把 /api 代理到本地后端；生产时前端产物由 FastAPI 同源托管，前端只用相对 URL。
const backend = process.env.GLEANERY_DEV_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: backend, changeOrigin: false } },
  },
  build: { outDir: "dist" },
});
