/**
 * Smoke spec: thinking display mode switcher (header + message context submenu).
 *
 * Scope decisions:
 * - Only verifies the switcher UI and context-menu submenu are wired end-to-end.
 *   Does NOT test rendering differences of the thinking panel (the stub backend
 *   serves no reasoning_content or tool_calls, so those assertions would be vacuous).
 * - Does NOT test the settings page dropdown — BasicTab unit tests cover that.
 * - Does NOT seed a non-default display mode — the test verifies the default
 *   fallback to `trace` (label `仅执行`).
 * - One monolithic test to avoid Electron cold-start overhead (60s project timeout,
 *   20-30s startup on CI). Each "step" is a clearly commented section.
 *
 * Coverage:
 *   Step 1 — Header switch visible with default label `仅执行`.
 *   Step 2 — Click switch → menu opens → pick `详细思考` → label updates.
 *   Step 3 — page.reload() → label persists (sessionStorage survives reload).
 *   Step 4 — Click switch → pick `跟随全局默认` → label returns to `仅执行`.
 *   Step 5 — Send a message → right-click assistant message → context menu
 *             opens → hover `思考展示` submenu trigger → submenu shows mode items.
 */
import { test, expect } from '@playwright/test';
import { launchElectronWithStub } from '../../../helpers/electron-launcher';

test('display mode: header switch + message context submenu', async () => {
  const { app, page, stub } = await launchElectronWithStub();

  // ── Seed localStorage (same shape as chat.spec.ts) ──────────────────
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

  // ── Navigate to a chat session ──────────────────────────────────────
  const sessionId = '00000000-0000-0000-0000-000000000001';
  await page.evaluate((sid: string) => {
    window.location.hash = `#/chat?session=${sid}`;
  }, sessionId);
  const chatInput = page.locator('[data-testid="chat-input"]');
  await expect(chatInput).toBeVisible({ timeout: 15_000 });
  await expect(chatInput).toBeEnabled({ timeout: 30_000 });

  // ── Step 1: Header switch visible with default label ────────────────
  const switchRoot = page.locator('[data-testid="display-mode-switch"]');
  await expect(switchRoot).toBeVisible({ timeout: 10_000 });
  const switchButton = page.locator('[data-testid="display-mode-button"]');
  await expect(switchButton).toContainText('仅执行', { timeout: 5_000 });

  // ── Step 2: Switch to detail mode ───────────────────────────────────
  await switchButton.click();
  const menu = page.locator('[data-testid="display-mode-menu"]');
  await expect(menu).toBeVisible({ timeout: 5_000 });

  await page.locator('[data-testid="display-mode-detail"]').click();
  await expect(menu).not.toBeVisible({ timeout: 5_000 });
  await expect(switchButton).toContainText('详细思考', { timeout: 5_000 });

  // ── Step 3: Persistence across reload ───────────────────────────────
  await page.reload();
  await page.waitForLoadState('load');
  // Re-navigate — reload may land on welcome page
  await page.evaluate((sid: string) => {
    window.location.hash = `#/chat?session=${sid}`;
  }, sessionId);
  await expect(switchRoot).toBeVisible({ timeout: 15_000 });
  await expect(switchButton).toContainText('详细思考', { timeout: 10_000 });

  // ── Step 4: Clear override via follow-global ────────────────────────
  const switchButton2 = page.locator('[data-testid="display-mode-button"]');
  await switchButton2.click();
  const menu2 = page.locator('[data-testid="display-mode-menu"]');
  await expect(menu2).toBeVisible({ timeout: 5_000 });

  await page.locator('[data-testid="display-mode-follow-global"]').click();
  await expect(menu2).not.toBeVisible({ timeout: 5_000 });
  await expect(switchButton2).toContainText('仅执行', { timeout: 5_000 });

  // ── Step 5: Message context menu submenu ────────────────────────────
  await chatInput.fill('hello');
  await page.locator('[data-testid="chat-send"]').click();

  const assistantMsg = page.locator('[data-testid="chat-message-assistant"]').last();
  await expect(assistantMsg).toContainText(/hi|hello|fixture/, { timeout: 10_000 });

  // Right-click the assistant message bubble to open Radix context menu.
  // The ContextMenu wraps the inner bubble ([data-quote-scope="message-body"]),
  // NOT the outer testid wrapper (which includes the avatar and gap).
  const assistantBubble = page.locator('[data-testid="chat-message-assistant"] [data-quote-scope="message-body"]').last();
  await expect(assistantBubble).toBeVisible({ timeout: 5_000 });
  const box = await assistantBubble.boundingBox();
  if (!box) throw new Error('assistant bubble has no bounding box');
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: 'right' });

  // The Radix context menu renders in a portal; find the submenu trigger by text.
  // Radix SubTrigger renders with role="menuitem" (same as regular items).
  const submenuTrigger = page.getByText('思考展示').last();
  await expect(submenuTrigger).toBeVisible({ timeout: 5_000 });

  // Hover the submenu trigger to open the Radix submenu
  await submenuTrigger.hover();

  // Submenu items should appear (Radix checkbox items render with role="menuitemcheckbox")
  const detailItem = page.locator('[role="menuitemcheckbox"]').filter({ hasText: '详细思考' });
  const traceItem = page.locator('[role="menuitemcheckbox"]').filter({ hasText: '仅执行' });
  const resultItem = page.locator('[role="menuitemcheckbox"]').filter({ hasText: '仅结果' });
  await expect(detailItem.first()).toBeVisible({ timeout: 5_000 });
  await expect(traceItem.first()).toBeVisible({ timeout: 2_000 });
  await expect(resultItem.first()).toBeVisible({ timeout: 2_000 });

  // ── Cleanup ─────────────────────────────────────────────────────────
  await app.close();
  stub.stop();
});
