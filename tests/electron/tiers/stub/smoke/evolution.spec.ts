import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.skip('evolution smoke: scheduler shows idle, draft adds to queue — TODO: /evolution route does not exist (only /scheduled); deferred per A1 decision', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/evolution');
  await expect(page.locator('[data-testid="scheduler-status"]'))
    .toContainText(/idle|running/, { timeout: 10_000 });

  const beforeCount = await page.locator('[data-testid="queue-item"]').count();
  await page.locator('[data-testid="evolution-trigger-draft"]').click();
  await expect(page.locator('[data-testid="queue-item"]')).toHaveCount(beforeCount + 1, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
