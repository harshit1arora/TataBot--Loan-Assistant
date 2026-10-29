import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// Dev server proxies the same paths nginx serves in the container image, so the browser
// only ever talks to one origin and there is no CORS surface to misconfigure.
const CORE = process.env.VITE_CORE_URL ?? "http://localhost:8000";
const CONVERSATION = process.env.VITE_CONVERSATION_URL ?? "http://localhost:8001";

export default defineConfig({
  server: {
    port: 8080,
    proxy: {
      "/auth": { target: CORE, changeOrigin: true },
      "/v1": { target: CORE, changeOrigin: true },
      "/download": { target: CORE, changeOrigin: true },
      "/chat": { target: CONVERSATION, changeOrigin: true },
      "/sessions": { target: CONVERSATION, changeOrigin: true },
    },
  },
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
