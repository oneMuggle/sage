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
    screenshot: 'on',
    video: 'off',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'electron',
      testDir: './tests/electron',
      timeout: 60_000,
      outputDir: './tests/electron/test-results',
    },
    {
      name: 'e2e',
      testDir: './tests/e2e',
      use: {
        baseURL: 'http://localhost:1420',
      },
      webServer: {
        command: 'npm run dev',
        url: 'http://localhost:1420',
        reuseExistingServer: !process.env.CI,
        timeout: 30_000,
      },
    },
  ],
});
