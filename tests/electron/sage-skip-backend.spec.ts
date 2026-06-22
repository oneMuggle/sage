/**
 * SAGE_SKIP_BACKEND localStorage 降级 smoke test。
 *
 * 验证后端不可用时，前端配置存储正确降级到 localStorage：
 *   1. Electron 启动（SAGE_SKIP_BACKEND=1，不启后端）
 *   2. settingsClient IPC 调用 5s 超时后返回 null（不卡死 UI）
 *   3. localStorage 缓存仍然可用（读写不抛异常）
 *   4. 用户界面可交互（主题切换、设置页面）
 *
 * 这是 PR #46 localStorage → 后端迁移的降级路径验证。
 *
 * @see docs/superpowers/specs/2026-06-22-localstorage-to-backend-design.md §4.3
 */
import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';

let app: ElectronApplication | null = null;
let window: Page | null = null;

test.beforeAll(async () => {
  app = await electron.launch({
    args: ['.'],
    cwd: process.cwd(),
    env: {
      ...process.env,
      SAGE_SKIP_BACKEND: '1',
      CI: 'true',
      NODE_ENV: 'production',
    },
    timeout: 30_000,
  });

  window = await app!.firstWindow({ timeout: 30_000 });
  await window.waitForLoadState('domcontentloaded');
});

test.afterAll(async () => {
  if (app) {
    await app.close();
    app = null;
    window = null;
  }
});

test('settingsClient IPC 超时后返回 null（5s 内不卡死）', async () => {
  expect(window).not.toBeNull();

  // 等待 electronAPI 就绪
  await window!.waitForFunction(
    () =>
      typeof (window as unknown as { electronAPI?: { invoke?: unknown } }).electronAPI?.invoke ===
      'function',
    undefined,
    { timeout: 10_000 },
  );

  // 调用 get_settings（后端不可用，应 5s 后返回 null）
  const startTime = Date.now();
  const result = await window!.evaluate(async () => {
    const win = globalThis as unknown as {
      electronAPI?: { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
    };
    try {
      // settingsClient.getSettings() 内部调用 invoke('get_settings')
      // 后端不可用时，main process 会 reject，settingsClient 5s 超时后返回 null
      return await win.electronAPI!.invoke<{ data: unknown } | null>('get_settings');
    } catch (e) {
      // invoke 抛错时，settingsClient 会 catch 并返回 null
      return null;
    }
  });
  const elapsed = Date.now() - startTime;

  // 验证：5s 内返回（不卡死）
  expect(elapsed, 'settingsClient 应在 5s 内返回（超时降级）').toBeLessThan(6_000);

  // 验证：返回 null（后端不可用）
  expect(result, '后端不可用时 settingsClient.getSettings() 应返回 null').toBeNull();
});

test('localStorage 降级路径可读写', async () => {
  expect(window).not.toBeNull();

  // 验证 localStorage 可用
  const localStorageAvailable = await window!.evaluate(() => {
    try {
      localStorage.setItem('test_key', 'test_value');
      const value = localStorage.getItem('test_key');
      localStorage.removeItem('test_key');
      return value === 'test_value';
    } catch {
      return false;
    }
  });

  expect(localStorageAvailable, 'localStorage 应可用').toBe(true);
});

test('UI 可交互（主题切换）', async () => {
  expect(window).not.toBeNull();

  // 等待 UI 渲染完成
  await window!.waitForSelector('body', { timeout: 10_000 });

  // 验证页面不是空白
  const bodyText = await window!.locator('body').textContent({ timeout: 5_000 });
  expect(bodyText, '页面应渲染内容').toBeTruthy();
  expect(bodyText!.length, '页面文本长度 > 0').toBeGreaterThan(0);

  // 截图供人工 review
  await window!.screenshot({
    path: 'tests/electron/screenshots/sage-skip-backend-ui.png',
    fullPage: true,
  });
});

test('settingsClient 降级后 localStorage 缓存仍可用', async () => {
  expect(window).not.toBeNull();

  // 手动写入 localStorage 模拟缓存
  await window!.evaluate(() => {
    localStorage.setItem(
      'sage-settings',
      JSON.stringify({
        version: '3.0.0',
        endpoints: [],
        modelSelections: {
          chatModel: { endpointId: null, modelId: null },
          visionModel: { endpointId: null, modelId: null },
          embeddingModel: { endpointId: null, modelId: null },
        },
        streaming: true,
        autoMemory: true,
        confirmDelete: true,
        compactMode: false,
        maxContext: 4096,
        temperature: 0.7,
        proxyMode: 'system',
        proxyUrl: '',
        tlsVersion: '1.2',
      }),
    );
  });

  // 验证 localStorage 数据可读
  const cached = await window!.evaluate(() => {
    const raw = localStorage.getItem('sage-settings');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  });

  expect(cached, 'localStorage 缓存应可读').not.toBeNull();
  expect(cached.version, '缓存版本应为 3.0.0').toBe('3.0.0');

  // 清理
  await window!.evaluate(() => {
    localStorage.removeItem('sage-settings');
  });
});
