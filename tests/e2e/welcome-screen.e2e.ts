import { test, expect } from '@playwright/test';

test.describe('Welcome screen', () => {
  test.beforeEach(async ({ page }) => {
    // Ensure each test starts with no current session
    await page.goto('/');
    await page.evaluate(() => {
      window.localStorage.removeItem('sage:current_session_id');
    });
  });

  test('shows welcome screen when no session is active', async ({ page }) => {
    await page.goto('/welcome');
    // Hero text
    await expect(page.getByText(/你好，我是 Claude/)).toBeVisible();
    // Textarea visible
    const textarea = page.getByRole('textbox');
    await expect(textarea).toBeVisible();
    // 3 recommendation cards
    const cards = page.getByTestId('recommendation-card');
    await expect(cards).toHaveCount(3);
    // Quick action bar
    await expect(page.getByRole('toolbar', { name: /quick actions/ })).toBeVisible();
  });

  test('clicking a recommendation prefills the input', async ({ page }) => {
    await page.goto('/welcome');
    const firstCard = page.getByTestId('recommendation-card').first();
    await firstCard.click();
    const textarea = page.getByRole('textbox') as HTMLTextAreaElement;
    const value = await textarea.inputValue();
    expect(value).toContain('帮我写代码');
  });

  test('sidebar new chat button navigates to /welcome', async ({ page }) => {
    await page.goto('/chat');
    // Click the sidebar's "新对话" button
    const newChatBtn = page.getByRole('button', { name: /新对话/ }).first();
    await newChatBtn.click();
    await expect(page).toHaveURL(/\/welcome/);
  });
});
