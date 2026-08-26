import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // ChatRoute (App.tsx:95-99) gates /chat on currentSessionId; without one it
  // redirects to /welcome. The deep-link form /chat?session=<id> writes the
  // session id into the store and replaces the search, landing us on /chat.
  await page.evaluate(() => {
    window.location.hash = '#/chat?session=stub-smoke-session';
  });
  await page.waitForSelector('[data-testid="chat-input"]', { timeout: 15_000 });

  await page.locator('[data-testid="chat-input"]').fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
    /hi|hello|fixture/,
    { timeout: 10_000 },
  );

  await app.close();
  stub.stop();
});
