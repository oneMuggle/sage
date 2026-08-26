import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // ChatRoute (App.tsx:83-99) gates /chat on currentSessionId; without one it
  // redirects to /welcome. The deep-link form /chat?session=<id> writes the
  // session id into the store and replaces the search, landing us on /chat.
  //
  // sessionId MUST be a UUID (see src/shared/api/utils.ts:66-70) — chatApi
  // validates the format before sending and rejects non-UUIDs with the
  // error '无效的会话ID格式'. The stub also creates sessions via uuid.uuid4().
  // We use a fixed UUID so the spec is deterministic across CI runs.
  const sessionId = '00000000-0000-0000-0000-000000000001';
  await page.evaluate((sid: string) => {
    window.location.hash = `#/chat?session=${sid}`;
  }, sessionId);
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
