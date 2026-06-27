import { test, expect } from '@playwright/test';

test.describe('LLM Wiki folder picker', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      (window as any).electronAPI = {
        selectDirectory: async (opts: any) => {
          (window as any).__lastSelectOpts = opts;
          return (window as any).__mockPicked ?? null;
        },
        invoke: async () => null,
        listen: async () => () => {},
        windowControls: {},
      };
    });
  });

  test('browse → fill input → check badge → create success', async ({ page }) => {
    await page.goto('/wiki');
    await page.getByRole('button', { name: /创建新项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = '/tmp/playwright-wiki'; });
    await page.getByTestId('browse-btn').click();

    const input = page.getByTestId('path-input');
    await expect(input).toHaveValue('/tmp/playwright-wiki');

    await page.route('**/api/v1/wiki/project/check**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          exists: false, writable: false, is_project: false,
          parent_writable: true, warning: null, error: null,
        }),
      }),
    );
    await page.route('**/api/v1/wiki/project/create', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'p1', name: 'pw', path: '/tmp/playwright-wiki',
          created_at: Date.now() / 1000, has_content: false,
        }),
      }),
    );
    await page.route('**/api/v1/wiki/recent-projects/record', (route) =>
      route.fulfill({ status: 204 }),
    );
    await page.route('**/api/v1/wiki/recent-projects', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    );

    await expect(page.getByTestId('status-ok')).toBeVisible({ timeout: 2000 });
    await page.getByRole('button', { name: /^创建项目$/ }).click();
    await expect(page).toHaveURL(/\/wiki\/project\//, { timeout: 5000 });
  });

  test('cancel dialog → input unchanged', async ({ page }) => {
    await page.goto('/wiki');
    await page.getByRole('button', { name: /打开现有项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = null; });
    const input = page.getByTestId('path-input');
    await expect(input).toHaveValue('');
    await page.getByTestId('browse-btn').click();
    await expect(input).toHaveValue('');
  });

  test('defaultPath is parent of most recent project', async ({ page }) => {
    await page.route('**/api/v1/wiki/recent-projects', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { path: '/data/projects/team-handbook/wiki', name: 'team-handbook',
            opened_at: Date.now() / 1000, intent: 'open' },
        ]),
      }),
    );
    await page.goto('/wiki');
    await page.getByRole('button', { name: /打开现有项目/ }).click();
    await page.evaluate(() => { (window as any).__mockPicked = '/data/projects/team-handbook'; });
    await page.getByTestId('browse-btn').click();
    const opts = await page.evaluate(() => (window as any).__lastSelectOpts);
    expect(opts.defaultPath).toBe('/data/projects');
  });
});
