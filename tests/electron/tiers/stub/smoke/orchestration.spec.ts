import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';
import orchFixture from '../../../fixtures/sample_orchestration.json' with { type: 'json' };

test('orchestration smoke: create run with 3 agents, lanes render', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/orchestration');
  await page.locator('[data-testid="orch-create"]').click();
  await page.locator('[data-testid="orch-plan"]').fill(orchFixture.plan);
  await page.locator('[data-testid="orch-submit"]').click();

  await expect(page.locator('[data-testid^="lane-"]')).toHaveCount(3, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
