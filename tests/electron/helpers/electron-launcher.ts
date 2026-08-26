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
 *   - We pass `args: ['.']` so Electron uses the project's package.json
 *     `main` field (dist-electron/electron/main.js).
 */
import { _electron as electron, ElectronApplication, Page } from '@playwright/test';
import { StubBackend } from './stub-backend';

export interface ElectronWithStub {
  app: ElectronApplication;
  page: Page;
  stub: StubBackend;
}

export async function launchElectronWithStub(): Promise<ElectronWithStub> {
  const stub = new StubBackend();
  await stub.start();
  const app = await electron.launch({
    args: ['.'],
    env: {
      ...process.env,
      SAGE_BACKEND_URL: stub.url,
      PYTHON_BACKEND_PORT: String(stub.port),
      SAGE_SKIP_BACKEND: '1',
    },
  });
  // Pick the Sage app window, NOT Chromium DevTools. When main.ts opens
  // DevTools in detach mode (isDev=true), it spawns a second top-level
  // BrowserWindow whose URL starts with `devtools://`. Playwright's
  // firstWindow() may return that window if it opens before the React app
  // finishes loading — yielding a DevTools page with no <a> tags and no
  // React route handlers. Filter to the first non-devtools window instead.
  const page = await waitForAppWindow(app, 30_000);
  return { app, page, stub };
}

async function waitForAppWindow(
  app: ElectronApplication,
  timeoutMs: number,
): Promise<Page> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const windows = app.windows();
    for (const w of windows) {
      const url = w.url();
      if (!url.startsWith('devtools://') && !url.startsWith('chrome://')) {
        return w;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(
    `Sage app window not found within ${timeoutMs}ms ` +
      `(saw ${app.windows().length} windows, all devtools:// or chrome://)`,
  );
}
