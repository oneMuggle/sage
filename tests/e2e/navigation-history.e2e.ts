import { test, expect } from '@playwright/test';

test.describe('Navigation History', () => {
  test('back button navigates to previous route', async ({ page }) => {
    await page.goto('/chat');
    // Sidebar links use Chinese labels (default locale = 'zh')
    await page.getByRole('link', { name: /设置/ }).click();
    await expect(page).toHaveURL(/\/settings/);

    const backBtn = page.getByLabel('后退');
    await backBtn.click();
    await expect(page).toHaveURL(/\/chat/);
  });

  test('back button is disabled on initial route', async ({ page }) => {
    await page.goto('/chat');
    const backBtn = page.getByLabel('后退');
    await expect(backBtn).toBeDisabled();
  });

  test('forward button navigates forward after going back', async ({ page }) => {
    await page.goto('/chat');
    await page.getByRole('link', { name: /设置/ }).click();
    await page.getByLabel('后退').click();
    await expect(page).toHaveURL(/\/chat/);

    const forwardBtn = page.getByLabel('前进');
    await expect(forwardBtn).not.toBeDisabled();
    await forwardBtn.click();
    await expect(page).toHaveURL(/\/settings/);
  });
});
