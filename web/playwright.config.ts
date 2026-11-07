import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: process.env.OFFICE_E2E_URL || "http://127.0.0.1:8765",
    screenshot: "off",
    viewport: { width: 1440, height: 900 },
  },
  webServer: undefined,
});
