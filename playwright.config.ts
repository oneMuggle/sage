import { defineConfig } from '@playwright/test';

/**
 * Playwright config — multi-project:
 *   - electron: smoke tests for Win7 IPC bridge contract (Phase 4)
 *   - e2e: browser-based E2E tests against Vite dev server
 *
 * electron project:
 *   - Uses playwright._electron API
 *   - SAGE_SKIP_BACKEND=1 (CI runner has no conda env)
 *   - Screenshots on failure + on each test
 *   - Timeout: 60s (Electron cold start on CI can take 20-30s)
 *
 * e2e project:
 *   - Runs against Vite dev server (http://localhost:1420)
 *   - Tests navigation, UI flows, etc. in a real browser (Chromium)
 *   - Timeout: 30s (no cold-start overhead)
 */
export default defineConfig({
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:1420',
    screenshot: 'on',
    video: 'off',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:1420',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: 'electron',
      testDir: './tests/electron',
      timeout: 60_000,
      // Allow 2 retries on CI to absorb pre-existing flaky Electron cold-start timing
      // (Windows runner can be slow during preload execution — waitForFunction 30s
      // covers most cases, but a retry catches the tail).
      retries: process.env.CI ? 2 : 0,
      outputDir: './tests/electron/test-results',
    },
    {
      name: 'e2e',
      testDir: './tests/e2e',
      use: {
        baseURL: 'http://localhost:1420',
      },
    },
    {
      name: 'e2e-root',
      testDir: './e2e',
      use: {
        baseURL: 'http://localhost:1420',
      },
    },
    // Tier-based Electron E2E projects (Tier 1: stub; Tier 2: live).
    // Stub projects DO need the top-level Vite dev server (Electron loads
    // the renderer from http://localhost:1420 in dev mode — main.ts:73,642).
    // The Python stub backend is a separate Node-side server spun up by
    // launchElectronWithStub() on a random port (SAGE_BACKEND_URL), and
    // lives alongside Vite on 1420 — not in place of it.
    // Live projects spawn the real sage-backend via per-project webServer.
    {
      name: 'electron-stub-smoke',
      testDir: './tests/electron/tiers/stub/smoke',
      timeout: 60_000,
      retries: process.env.CI ? 1 : 0,
      outputDir: './tests/electron/tiers/stub/smoke/test-results',
    },
    {
      name: 'electron-stub-deep',
      testDir: './tests/electron/tiers/stub/deep',
      timeout: 120_000,
      retries: process.env.CI ? 1 : 0,
      outputDir: './tests/electron/tiers/stub/deep/test-results',
    },
    {
      name: 'electron-live-boot',
      testDir: './tests/electron/tiers/live/boot-smoke',
      timeout: 60_000,
      retries: 0,
      outputDir: './tests/electron/tiers/live/boot-smoke/test-results',
    },
    {
      name: 'electron-live-deep',
      testDir: './tests/electron/tiers/live/deep',
      timeout: 180_000, // 3 min for LLM API calls (R24)
      retries: 0,
      outputDir: './tests/electron/tiers/live/deep/test-results',
    },
  ],
});
