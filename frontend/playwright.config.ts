import { defineConfig, devices } from "@playwright/test";

// The backend is mocked per test (e2e/mock-api.ts), so only the Vite dev server is needed.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: { command: "npm run dev -- --port 5173 --strictPort", url: "http://localhost:5173", reuseExistingServer: true },
});
