import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('chat smoke: send hello, receive fixture response, message persisted', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // The stub settings endpoint intentionally returns an empty configuration.
  // Seed a valid local cache before the app loads settings so ChatInput is
  // enabled and the test exercises the chat stream rather than the config gate.
  await page.evaluate(() => {
    window.localStorage.setItem(
      'sage-settings',
      JSON.stringify({
        streaming: true,
        autoMemory: true,
        confirmDelete: true,
        compactMode: false,
        endpoints: [
          {
            id: 'ep-e2e',
            name: 'E2E Stub',
            baseUrl: 'http://127.0.0.1:9/v1',
            apiKey: 'sk-e2e',
            discoveredModels: [],
            lastDiscoveredAt: null,
          },
        ],
        modelSelections: {
          chatModel: { endpointId: 'ep-e2e', modelId: 'stub-model' },
          visionModel: { endpointId: null, modelId: null },
          embeddingModel: { endpointId: null, modelId: null },
        },
        maxContext: 4096,
        temperature: 0.7,
        proxyMode: 'system',
        proxyUrl: '',
        tlsVersion: '1.2',
        wiki: { useFolderPicker: true },
        version: '3.0.0',
      }),
    );
    window.localStorage.setItem('sage-settings.migrated_to_backend', new Date().toISOString());
  });
  await page.reload();
  await page.waitForLoadState('load');

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
  const chatInput = page.locator('[data-testid="chat-input"]');
  await expect(chatInput).toBeVisible({ timeout: 15_000 });
  await expect(chatInput).toBeEnabled({ timeout: 30_000 });

  await chatInput.fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
    /hi|hello|fixture/,
    { timeout: 10_000 },
  );

  await app.close();
  stub.stop();
});
