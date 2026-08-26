import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';
import orchFixture from '../../../fixtures/sample_orchestration.json' with { type: 'json' };

test('orchestration smoke: create run with 3 agents, lanes render', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // HashRouter: navigate via window.location.hash. /orchestration is a
  // progressive-disclosure nav item (ADVANCED_FEATURE_BY_PATH in Sidebar.tsx)
  // hidden until first visit, so the sidebar <a> may not render at all.
  // Setting the hash triggers React Router regardless of disclosure state.
  // waitForSelector replaces the implicit click() which had actionTimeout=0.
  await page.evaluate(() => {
    window.location.hash = '#/orchestration';
  });
  await page.waitForSelector('[data-testid="orch-create"]', { timeout: 15_000 });
  await page.locator('[data-testid="orch-create"]').click();
  await page.waitForSelector('[data-testid="orch-plan"]', { timeout: 10_000 });
  await page.locator('[data-testid="orch-plan"]').fill(orchFixture.plan);
  await page.locator('[data-testid="orch-submit"]').click();

  await expect(page.locator('[data-testid^="lane-lane_"]')).toHaveCount(3, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
