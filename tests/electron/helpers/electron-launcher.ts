/**
 * Helper: launch Electron with a running stub backend wired in via env vars.
 *
 * Usage:
 *   const { app, page, stub } = await launchElectronWithStub();
 *   ... exercise the app ...
 *   await app.close();
 *   stub.stop();
 *
 * Environment contract:
 *   SAGE_BACKEND_URL   — stub base URL (renderer picks it up)
 *   PYTHON_BACKEND_PORT — port only (Electron main.ts constructs backend URL)
 *   SAGE_SKIP_BACKEND   — "1" so Electron does NOT spawn a real backend process
 *                         (we have a stub on this port already)
 *
 * Notes:
 *   - The Electron app must already be built (`npm run build:electron`).
 *     The launch will fail with ENOENT otherwise.
 *   - We pass `args: [MAIN_JS]` (NOT `args: ['.']`). When Electron is launched
 *     with `.` as the app arg it sets `process.defaultApp = true`, which
 *     triggers a fast-exit path that closes the main process after the
 *     first log line — Playwright then sees `electron.launch: Process failed
 *     to launch!` (ws disconnected code=1006, exitCode=0). The Office spec
 *     (tests/electron/tiers/stub/smoke/office.spec.ts:215) already uses an
 *     explicit `mainJs` path; the helper must match.
 *   - `cwd` is set to the project root explicitly. Without it, Playwright's
 *     electron.launch inherits the test runner's cwd, which can shift between
 *     `npm run test:smoke` (project root) and direct `npx playwright` invocations.
 */
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { _electron as electron, ElectronApplication, Page } from '@playwright/test';
import { StubBackend } from './stub-backend';

const _filename = typeof __filename !== 'undefined' ? __filename : fileURLToPath(import.meta.url);
const _dirname = typeof __dirname !== 'undefined' ? __dirname : path.dirname(_filename);

// Project root = two levels up from tests/electron/helpers/electron-launcher.ts.
// Resolved at module load so the path is stable regardless of where Playwright
// is invoked from.
const PROJECT_ROOT = path.resolve(_dirname, '..', '..', '..');
const MAIN_JS = path.join(PROJECT_ROOT, 'dist-electron', 'electron', 'main.js');

export interface ElectronWithStub {
  app: ElectronApplication;
  page: Page;
  stub: StubBackend;
}

export interface LaunchElectronWithStubOptions {
  /**
   * Extra env vars merged over the default launch env. Used by the demo-mode
   * specs (round-3 N1): `SAGE_DEMO_MODE=1` makes main.ts treat the process as
   * a demo run (electron/main.ts isDemoProcess) and forward
   * `--sage-demo-mode=1` to the renderer, so `isDemoMode()` is true from the
   * first paint and src/shared/api/demoInterceptors.ts answers every
   * registered channel (all office_* channels live there — the Python stub
   * has no /office routes).
   */
  env?: Record<string, string>;
}

export async function launchElectronWithStub(
  options: LaunchElectronWithStubOptions = {},
): Promise<ElectronWithStub> {
  if (!existsSync(MAIN_JS)) {
    throw new Error(
      `${MAIN_JS} not found — run \`npm run build:electron\` before launching the smoke suite.`,
    );
  }

  const stub = new StubBackend();
  await stub.start();
  const app = await electron.launch({
    // Explicit path (NOT '.') — see Notes above for why this matters.
    args: [MAIN_JS],
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      SAGE_BACKEND_URL: stub.url,
      PYTHON_BACKEND_PORT: String(stub.port),
      SAGE_SKIP_BACKEND: '1',
      ...options.env,
    },
    timeout: 30_000,
  });
  // Pick the Sage app window, NOT Chromium DevTools or the initial blank page.
  // When main.ts opens DevTools in detach mode (isDev=true), it spawns a second
  // top-level BrowserWindow whose URL starts with `devtools://`. Playwright's
  // firstWindow() may return that window or the initial `about:blank` page if
  // either opens before the React app finishes loading. Filter to the first
  // non-app window instead.
  const page = await waitForAppWindow(app, 30_000);
  return { app, page, stub };
}

async function waitForAppWindow(app: ElectronApplication, timeoutMs: number): Promise<Page> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const windows = app.windows();
    for (const w of windows) {
      const url = w.url();
      if (url !== 'about:blank' && !url.startsWith('devtools://') && !url.startsWith('chrome://')) {
        return w;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(
    `Sage app window not found within ${timeoutMs}ms ` +
      '(all observed windows were filtered as non-app pages)',
  );
}
