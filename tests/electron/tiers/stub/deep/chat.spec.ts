// tests/electron/tiers/stub/deep/chat.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub, type ElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('chat deep', () => {
  let app: ElectronWithStub['app'];
  let page: ElectronWithStub['page'];
  let stub: ElectronWithStub['stub'];
  let sessionId: string;

  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
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
              id: 'ep-deep-e2e',
              name: 'Deep E2E Stub',
              baseUrl: 'http://127.0.0.1:9/v1',
              apiKey: 'sk-deep-e2e',
              discoveredModels: [],
              lastDiscoveredAt: null,
            },
          ],
          modelSelections: {
            chatModel: { endpointId: 'ep-deep-e2e', modelId: 'stub-model' },
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
  });

  test.beforeEach(async () => {
    sessionId = crypto.randomUUID();
    await page.goto(`http://localhost:1420/#/chat?session=${sessionId}`);
    // ChatRoute consumes the query parameter and intentionally replaces it.
    await expect(page).toHaveURL(/http:\/\/localhost:1420\/#\/chat$/);
    await expect(page.locator('[data-testid="chat-input"]')).toBeEnabled({ timeout: 30_000 });
  });

  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
  });

  test('聊天流最终显示 assistant 内容', async () => {
    await page.locator('[data-testid="chat-input"]').fill('tell me a long story');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
      'hello from stub backend fixture',
      { timeout: 10_000 },
    );
  });

  test.skip('工具调用 mock 响应', async () => {
    // 当前 stub 的工具流由 PERM_TEST_MARKER 触发，且消息 UI 没有 tool-call/tool-result 标记。
    await page.goto('http://localhost:1420/#/chat');
    await page.locator('[data-testid="chat-input"]').fill('@tool:echo hello');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="tool-call"]').first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('[data-testid="tool-result"]').first()).toContainText('hello');
  });

  test('发送消息后重新进入仍显示 assistant 内容', async () => {
    await page.locator('[data-testid="chat-input"]').fill('first message');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
      'hello from stub backend fixture',
      { timeout: 10_000 },
    );

    // 当前 stub 流会立即完成；这里验证同一 session 的消息在重新进入后仍可见。
    await page.goto('http://localhost:1420/#/welcome');
    await page.goto(`http://localhost:1420/#/chat?session=${sessionId}`);
    await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
      'hello from stub backend fixture',
    );
  });

  test.skip('会话切换', async () => {
    // 应用没有独立的 /sessions 路由；会话列表只在 Layout 侧边栏中呈现。
    await page.goto('http://localhost:1420/#/sessions');
    await page.locator('[data-testid="session-item"]').first().click();
    await expect(page).toHaveURL(/\/chat\?session=/);
  });

  test.skip('上下文压缩触发', async () => {
    // stub chat 流不会发出 memory-consolidation-event，当前没有可观测契约。
    await page.goto('http://localhost:1420/#/chat');
    // 发 5 条长消息，触发 working memory 压缩
    for (let i = 0; i < 5; i++) {
      await page.locator('[data-testid="chat-input"]').fill('Long message '.repeat(50) + i);
      await page.locator('[data-testid="chat-send"]').click();
      await page.waitForTimeout(500);
    }
    await expect(page.locator('[data-testid="memory-consolidation-event"]')).toBeVisible({
      timeout: 30_000,
    });
  });
});
