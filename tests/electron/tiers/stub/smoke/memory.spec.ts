import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('memory smoke: add memory item appears in episodic list', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // HashRouter: sidebar nav is <Link to={path}> → <a href="#/memory">.
  // Use window.location.hash so we don't depend on sidebar disclosure or
  // actionTimeout=0 default. waitForSelector replaces the implicit click().
  await page.evaluate(() => {
    window.location.hash = '#/memory';
  });
  await page.waitForSelector('[data-testid="memory-add"]', { timeout: 15_000 });
  await page.locator('[data-testid="memory-add"]').click();

  await page.waitForSelector('[data-testid="memory-content"]', { timeout: 10_000 });
  await page.locator('[data-testid="memory-content"]').fill('test memory item');
  await page.locator('[data-testid="memory-submit"]').click();

  await expect(page.locator('[data-testid="memory-episodic-item"]').last()).toContainText(
    'test memory item',
    { timeout: 10_000 },
  );

  await app.close();
  stub.stop();
});
