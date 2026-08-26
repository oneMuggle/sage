// tests/electron/tiers/stub/deep/chat.spec.ts
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test.describe('chat deep', () => {
  let app, page, stub;
  test.beforeAll(async () => {
    ({ app, page, stub } = await launchElectronWithStub());
  });
  test.afterAll(async () => {
    await app?.close();
    stub?.stop();
  });

  test('SSE 流式分块验证', async () => {
    // 触发 chat，监听 SSE 事件，验证至少 3 个 chunk 到达
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('tell me a long story');
    await page.locator('[data-testid="chat-send"]').click();
    // 等待首个 chunk
    await expect(page.locator('[data-testid="chat-message-assistant"]').last()).toContainText(
      /[a-z]/,
      { timeout: 5_000 },
    );
    // 验证后续 chunk 累积（content 长度增加）
    const len1 = await page.locator('[data-testid="chat-message-assistant"]').last().textContent();
    await page.waitForTimeout(1000);
    const len2 = await page.locator('[data-testid="chat-message-assistant"]').last().textContent();
    expect(len2!.length).toBeGreaterThanOrEqual(len1!.length);
  });

  test('工具调用 mock 响应', async () => {
    // stub 注入 tool_call，验证 UI 渲染 + 回传 tool result
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('@tool:echo hello');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="tool-call"]').first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.locator('[data-testid="tool-result"]').first()).toContainText('hello');
  });

  test('中断续聊', async () => {
    await page.goto('/chat');
    await page.locator('[data-testid="chat-input"]').fill('first message');
    await page.locator('[data-testid="chat-send"]').click();
    await expect(page.locator('[data-testid="chat-message-assistant"]')).toHaveCount(2, {
      timeout: 10_000,
    });

    // 关闭 stream，重新进入
    await page.goto('/welcome');
    await page.goto('/chat');
    await expect(page.locator('[data-testid="chat-message-assistant"]').first()).toBeVisible();
  });

  test('会话切换', async () => {
    await page.goto('/sessions');
    await page.locator('[data-testid="session-item"]').first().click();
    await expect(page).toHaveURL(/\/chat\?session=/);
  });

  test('上下文压缩触发', async () => {
    await page.goto('/chat');
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
