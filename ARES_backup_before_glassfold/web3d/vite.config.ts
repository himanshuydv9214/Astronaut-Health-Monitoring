import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app is served by FastAPI: index at "/", assets under /app (ares/web3d_dist). `npm run dev` proxies the API.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: { outDir: "../ares/web3d_dist", emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/anatomy-assets": "http://127.0.0.1:8000",
      "/vendor": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
