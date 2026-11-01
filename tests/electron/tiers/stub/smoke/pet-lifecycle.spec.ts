import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

import { test, expect } from '@playwright/test';

import { launchElectronWithStub } from '../../../helpers/electron-launcher';

/**
 * Dev-mode close-to-tray preference lives in <repo>/data/ and is NOT covered
 * by SAGE_USER_DATA_DIR. A developer who enabled it would see the main
 * window hide instead of close and this spec would time out.
 */
function forceCloseToTrayDisabled(): () => void {
  const file = join(process.cwd(), 'data', 'sage-close-to-tray.json');
  const previous = existsSync(file) ? readFileSync(file, 'utf8') : null;
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify({ enabled: false })}\n`);
  return () => {
    if (previous === null) rmSync(file, { force: true });
    else writeFileSync(file, previous);
  };
}

/**
 * Regression: the pet overlay is its own BrowserWindow, so it must not keep
 * the process alive after the user closes the main window. Before the fix,
 * window-all-closed never fired and the app stayed running with no UI.
 */
test('closing the main window quits the app even with the pet overlay open', async () => {
  // Dev-mode userData resolves to <repo>/data; isolate this spec so it never
  // rewrites the developer's real pet-config.json.
  const userDataDir = mkdtempSync(join(tmpdir(), 'sage-pet-lifecycle-'));
  const restoreCloseToTray = forceCloseToTrayDisabled();
  const { app, page, stub } = await launchElectronWithStub({
    env: { SAGE_USER_DATA_DIR: userDataDir },
  });

  try {
    await page.waitForLoadState('load');

    // Enabling the desktop pet creates the (focusable:false) overlay window.
    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({ enabled: true, displayMode: 'desktop' });
    });

    await expect
      .poll(
        async () =>
          app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows().some((win) =>
              win.webContents.getURL().includes('/pet.html'),
            ),
          ),
        { timeout: 15_000 },
      )
      .toBe(true);

    const closed = new Promise<void>((resolve) => {
      app.on('close', () => resolve());
    });

    await app.evaluate(({ BrowserWindow }) => {
      const main = BrowserWindow.getAllWindows().find((win) => {
        const url = win.webContents.getURL();
        return (
          !url.includes('/pet.html') &&
          !url.startsWith('devtools://') &&
          !url.startsWith('chrome://') &&
          url !== 'about:blank'
        );
      });
      main?.close();
    });

    await Promise.race([
      closed,
      new Promise<void>((_, reject) =>
        setTimeout(
          () => reject(new Error('app stayed alive after the main window closed')),
          16_000,
        ),
      ),
    ]);
  } finally {
    await app.close().catch(() => undefined);
    stub.stop();
    rmSync(userDataDir, { recursive: true, force: true });
    restoreCloseToTray();
  }
});
