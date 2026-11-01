<<<<<<< HEAD
=======
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

>>>>>>> origin/main
import { test, expect } from '@playwright/test';

import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('pet background: orchestration lanes appear as background tasks', async () => {
<<<<<<< HEAD
  const { app, page, stub } = await launchElectronWithStub();
=======
  // Isolate pet-config.json: a leftover config equal to the values this test
  // sets (enabled + in-app) would suppress the immediate refresh and the
  // assertion would wait for the 20s background poll.
  const userDataDir = mkdtempSync(join(tmpdir(), 'sage-pet-background-'));
  const { app, page, stub } = await launchElectronWithStub({
    env: { SAGE_USER_DATA_DIR: userDataDir },
  });
>>>>>>> origin/main

  try {
    await page.waitForLoadState('load');

    // Create a planner run (3 ready lanes) in the shared stub backend.
    const created = await fetch(`${stub.url}/api/v1/orchestration/lanes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: 'E2E 编排任务' }),
    });
    expect(created.ok).toBe(true);
    const body = (await created.json()) as { team_id?: string };
    expect(body.team_id).toBeTruthy();

    // Enabling the pet triggers an immediate background refresh. In-app mode
    // avoids opening the overlay window while still emitting snapshots.
    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({ enabled: true, displayMode: 'in-app' });
    });

    await expect
      .poll(
        async () =>
          page.evaluate(async () => {
            const state = await window.electronAPI?.pet?.getState();
            return (state?.tasks ?? []).map((task) => `${task.kind}:${task.title}:${task.status}`);
          }),
        { timeout: 15_000 },
      )
      .toContain('orchestration:E2E 编排任务:queued');

    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({ enabled: false });
    });
  } finally {
    await app.close();
    stub.stop();
<<<<<<< HEAD
=======
    rmSync(userDataDir, { recursive: true, force: true });
>>>>>>> origin/main
  }
});
