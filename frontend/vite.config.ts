import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on 8756; proxy API + media + SSE so the app is same-origin
// in dev (no CORS surprises) and trivially wrappable later.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8756", changeOrigin: true },
      "/media": { target: "http://127.0.0.1:8756", changeOrigin: true },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
