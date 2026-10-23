import { defineConfig, devices } from "@playwright/test";

const MOCK_PORT = 8765;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // Synthesized speech is checked through its requests; let the audio clock run without a gesture.
        launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] },
      } }],
  webServer: [
    {
      command: "npx tsx tests/mock-backend.ts",
      url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
      env: { MOCK_PORT: String(MOCK_PORT) },
      reuseExistingServer: false,
    },
    {
      command: `npx next build && npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 240_000,
      reuseExistingServer: false,
      env: {
        NEXT_DIST_DIR: ".next-e2e",
        MEMORIA_API_URL: `http://127.0.0.1:${MOCK_PORT}`,
        NEXT_PUBLIC_MEMORIA_WS_ORIGIN: `ws://127.0.0.1:${MOCK_PORT}`,
      },
    },
  ],
});
