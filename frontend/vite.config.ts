/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, API calls go through the Vite server to FastAPI, so no CORS setup is needed.
const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: { include: ["src/**/*.test.ts"] }, // e2e/ is Playwright's
  server: {
    proxy: {
      "/auth": API,
      "/users": API,
      "/sessions": API,
      "/resumes": API,
      "/job-descriptions": API,
      "/ws": { target: API.replace("http", "ws"), ws: true },
    },
  },
});
