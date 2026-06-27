/**
 * Electron smoke test (Phase 4 lightweight CI smoke).
 *
 * Verifies the Win7 IPC bridge contract end-to-end:
 *   1. Electron launches without crashing
 *   2. BrowserWindow appears within 30s
 *   3. window.electronAPI is exposed by preload (preload.ts loaded)
 *   4. Frontend HTML loaded (not blank/white)
 *   5. screenshot saved for human review
 *
 * What this DOES NOT verify:
 *   - Backend spawn + /health (SAGE_SKIP_BACKEND=1 — CI has no conda env)
 *   - chat-stream-{id} NDJSON relay (requires live backend)
 *   - Win7-specific GPU flags (Electron 21 + Win7 D3D11 — covered by Phase 5
 *     self-hosted Win7 runner smoke test)
 *
 * @see docs/superpowers/plans/2026-06-13_*.md (Phase 4 in plan)
 */
import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';

let app: ElectronApplication | null = null;

test.beforeAll(async () => {
  app = await electron.launch({
    args: ['.'],
    cwd: process.cwd(),
    env: {
      ...process.env,
      SAGE_SKIP_BACKEND: '1',
      CI: 'true',
      NODE_ENV: 'production',
    },
    timeout: 30_000,
  });
});

test.afterAll(async () => {
  if (app) {
    await app.close();
    app = null;
  }
});

test('Electron launches and exposes electronAPI', async () => {
  expect(app, 'electron app must have launched').not.toBeNull();

  // Wait for first BrowserWindow
  const window = await app!.firstWindow({ timeout: 30_000 });
  await window.waitForLoadState('domcontentloaded');

  // Wait for electronAPI to be exposed by preload (contextBridge.exposeInMainWorld
  // is called synchronously but Playwright's firstWindow may resolve before
  // preload finishes — waitForFunction polls until the API is on window).
  await window.waitForFunction(
    () =>
      typeof (window as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI?.invoke ===
      'function',
    undefined,
    { timeout: 10_000 },
  );

  // Verify electronAPI.listen also exposed
  const hasListen = await window.evaluate(() => {
    const win = globalThis as unknown as {
      electronAPI?: { listen: unknown };
    };
    return typeof win.electronAPI?.listen === 'function';
  });
  expect(hasListen, 'window.electronAPI.listen must be a function').toBe(true);

  // Verify frontend HTML rendered (not blank)
  const bodyText = await window.locator('body').textContent({ timeout: 5_000 });
  expect(bodyText, 'frontend body must have rendered some text').toBeTruthy();
  expect(bodyText!.length, 'frontend body text length > 0').toBeGreaterThan(0);

  // Take screenshot for human review
  await window.screenshot({
    path: 'tests/electron/screenshots/smoke-launch.png',
    fullPage: true,
  });
});

test('invoke IPC bridge round-trips through main process', async () => {
  expect(app).not.toBeNull();
  const window = await app!.firstWindow({ timeout: 10_000 });
  await window.waitForLoadState('domcontentloaded');

  // Wait for electronAPI ready (same as first test)
  await window.waitForFunction(
    () =>
      typeof (window as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI?.invoke ===
      'function',
    undefined,
    { timeout: 10_000 },
  );

  // electronAPI.invoke calls ipcRenderer.invoke('sage:invoke', {cmd, args}).
  // Main process will throw "Unknown IPC command" for an unrecognized cmd —
  // that's expected and proves the bridge is wired through main.
  const errorMsg = await window.evaluate(async () => {
    const win = globalThis as unknown as {
      electronAPI?: { invoke: (cmd: string) => Promise<unknown> };
    };
    try {
      await win.electronAPI!.invoke('definitely_not_a_real_command');
      return null; // no error — bridge bypassed main??
    } catch (e) {
      return e instanceof Error ? e.message : String(e);
    }
  });

  // Either we got an error message (bridge works, main rejected cmd)
  // or main allowed it (shouldn't happen for unknown cmd)
  expect(errorMsg, 'invoke must route through main process; unknown cmd should throw').toMatch(
    /Unknown IPC command|definitely_not_a_real_command/i,
  );
});
