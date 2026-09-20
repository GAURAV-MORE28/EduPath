import { defineConfig } from "@playwright/test";

/**
 * Visual and journey checks run against a live stack (no mocks):
 *   backend:  uvicorn app.main:app  (seeded catalog)   -> API_URL, default http://localhost:8000
 *   frontend: npm run build && npm run start           -> BASE_URL, default http://localhost:3000
 * The journey spec expects a fresh database (no learner yet).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
