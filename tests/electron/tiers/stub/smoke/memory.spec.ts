import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('memory smoke: add memory item appears in episodic list', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // HashRouter: sidebar nav is <Link to={path}> → <a href="#/memory">.
  // page.goto('/memory') fails (relative URL invalid in Electron Page context).
  await page.locator('a[href*="/memory"]').click();
  await page.locator('[data-testid="memory-add"]').click();
  await page.locator('[data-testid="memory-content"]').fill('test memory item');
  await page.locator('[data-testid="memory-submit"]').click();

  await expect(page.locator('[data-testid="memory-episodic-item"]').last()).toContainText(
    'test memory item',
    { timeout: 10_000 },
  );

  await app.close();
  stub.stop();
});
