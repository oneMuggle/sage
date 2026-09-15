import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';
import wikiFixture from '../../../fixtures/sample_wiki_doc.json' with { type: 'json' };

test.skip('wiki smoke: ingest doc, search returns hit — TODO: /wiki route does not exist (only /knowledge); deferred per A1 decision', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/wiki');
  await page.locator('[data-testid="wiki-content"]').fill(wikiFixture.body);
  await page.locator('[data-testid="wiki-ingest"]').click();
  await page.locator('[data-testid="wiki-search"]').fill('E2E');
  await page.locator('[data-testid="wiki-search-btn"]').click();

  await expect(page.locator('[data-testid="wiki-result"]').first()).toBeVisible({ timeout: 10_000 });

  await app.close();
  stub.stop();
});
