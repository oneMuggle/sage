import { test, expect } from '@playwright/test';

interface SettingsIpcCall {
  command: string;
  args: Record<string, unknown>;
}

interface SettingsTestWindow extends Window {
  __settingsIpcCalls: SettingsIpcCall[];
}

const LEGACY_SNAKE_PAYLOAD = {
  endpoints: [
    {
      id: 'e1',
      name: 'Legacy endpoint',
      base_url: 'https://legacy.example.com/v1',
      api_key: 'test-legacy-key',
      discovered_models: [],
      last_discovered_at: 0,
    },
  ],
  model_selections: {
    chat_model: { endpoint_id: 'e1', model_id: 'm1' },
    vision_model: { endpoint_id: null, model_id: null },
    embedding_model: { endpoint_id: null, model_id: null },
  },
  streaming: true,
};

const CAMELCASE_PAYLOAD = {
  endpoints: [
    {
      id: 'e2',
      name: 'Camel endpoint',
      baseUrl: 'https://camel.example.com/v1',
      apiKey: 'test-camel-key',
      discoveredModels: [],
      lastDiscoveredAt: 0,
    },
  ],
  modelSelections: {
    chatModel: { endpointId: 'e2', modelId: 'm2' },
    visionModel: { endpointId: null, modelId: null },
    embeddingModel: { endpointId: null, modelId: null },
  },
  streaming: false,
};

test.describe('Settings schema canonicalization', () => {
  test.beforeEach(async ({ page }) => {
    // Browser E2E has no Electron preload; expose only the IPC calls this spec needs.
    await page.addInitScript(() => {
      const testWindow = window as unknown as SettingsTestWindow;
      testWindow.__settingsIpcCalls = [];
      window.localStorage.removeItem('sage-settings');
      window.localStorage.removeItem('sage-settings.migrated_to_backend');
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        value: {
          invoke: async (command: string, args: Record<string, unknown> = {}) => {
            if (command === 'get_settings') {
              const response = await fetch('/api/v1/settings');
              if (!response.ok) {
                throw new Error(`get_settings ${response.status}`);
              }
              return { data: await response.json() };
            }
            if (command === 'set_settings') {
              testWindow.__settingsIpcCalls.push({ command, args });
              return { status: 'ok' };
            }
            if (command === 'list_sessions') return [];
            if (command === 'get_preference') return { value: null };
            if (command === 'theme_list') return [];
            throw new Error(`Unexpected IPC command: ${command}`);
          },
          listLogFiles: async () => [],
          listen: async () => () => {},
          windowControls: {},
        },
      });
    });
  });

  test('历史 snake localStorage 在无远端时触发自动迁移', async ({ page }) => {
    // Init scripts run in the browser context, so serialize the Node-side fixture explicitly.
    await page.addInitScript((data) => {
      window.localStorage.setItem('sage-settings', data);
    }, JSON.stringify(LEGACY_SNAKE_PAYLOAD));

    // Do not mock GET here: the unavailable browser backend exercises the local fallback path.
    await page.goto('/#/settings');
    await expect(page.getByText('设置')).toBeVisible();
    await page.waitForFunction(
      () => Boolean(window.localStorage.getItem('sage-settings.migrated_to_backend')),
      undefined,
      { timeout: 5_000 },
    );

    const migrationPayload = await page.evaluate(() => {
      const calls = (window as unknown as SettingsTestWindow).__settingsIpcCalls;
      return calls.find((call) => call.command === 'set_settings')?.args ?? null;
    });
    expect(migrationPayload).not.toBeNull();
    expect(migrationPayload).toMatchObject({
      endpoints: [{ base_url: 'https://legacy.example.com/v1', api_key: 'test-legacy-key' }],
      model_selections: {
        chat_model: { endpoint_id: 'e1', model_id: 'm1' },
      },
    });
  });

  test('mocked backend returns camelCase settings directly', async ({ page }) => {
    let settingsRequestCount = 0;
    await page.route('**/api/v1/settings', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      settingsRequestCount += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CAMELCASE_PAYLOAD),
      });
    });

    await page.goto('/#/settings');
    await expect(page.getByText('设置')).toBeVisible();
    await page.getByRole('button', { name: '端点' }).click();
    await expect(page.getByText('https://camel.example.com/v1')).toBeVisible();
    expect(settingsRequestCount).toBeGreaterThan(0);
  });
});
