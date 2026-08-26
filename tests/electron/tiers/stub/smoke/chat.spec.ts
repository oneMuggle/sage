import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // HashRouter: sidebar nav is <Link to={path}> → <a href="#/chat">.
  // page.goto('/chat') fails (relative URL invalid in Electron Page context).
  await page.locator('a[href*="/chat"]').click();
  await page.locator('[data-testid="chat-input"]').fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  await expect(page.locator('[data-testid="chat-message-assistant"]').last())
    .toContainText(/hi|hello|fixture/, { timeout: 10_000 });

  await app.close();
  stub.stop();
});
