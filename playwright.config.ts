import { defineConfig } from '@playwright/test';

/**
 * Playwright config for Electron smoke tests (Phase 4).
 *
 * - Single project: electron (uses playwright._electron API)
 * - Screenshots on failure + on each test (saved to tests/electron/screenshots/)
 * - Timeout: 60s — Electron cold start on CI Windows runner can take 20-30s
 * - SAGE_SKIP_BACKEND=1 must be set so main.ts doesn't try to spawn FastAPI
 *   (CI runner doesn't have sage-backend conda env; smoke test verifies the
 *   IPC bridge contract, not backend integration)
 */
export default defineConfig({
  testDir: './tests/electron',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'list',
  use: {
    screenshot: 'on',
    video: 'off',
    trace: 'retain-on-failure',
  },
  outputDir: './tests/electron/test-results',
});
