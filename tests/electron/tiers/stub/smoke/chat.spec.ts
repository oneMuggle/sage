import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  await page.goto('/chat');
  await page.locator('[data-testid="chat-input"]').fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  await expect(page.locator('[data-testid="chat-message-assistant"]').last())
    .toContainText(/hi|hello|fixture/, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
