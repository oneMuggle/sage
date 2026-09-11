// e2e/hermetic/providers-manager.e2e.ts
//
// Phase 3 T4.1 — providers manager UI E2E journey (hermetic).
//
// What it covers:
//   1. Settings → Providers tab is visible (feature flag 全开 → ON by default).
//   2. Built-in default provider (Official) renders with current default marker.
//   3. Add GitHub provider via prompts → row appears in list.
//   4. Set as default → default marker moves to the new provider.
//   5. Test connection → IPC invoked and ok alert shown.
//   6. Remove provider → confirm dialog → row disappears.
//
// Note: IPC is mocked via window.electronAPI.providers.* shape used by the
// React component. We do not exercise the real Electron preload; that path
// is covered by Phase 1+2 unit tests under electron/update/__tests__/.

import { test, expect } from '@playwright/test';

interface ProvidersCall {
  cmd: 'list' | 'add' | 'remove' | 'setDefault' | 'test';
  payload?: unknown;
}

interface ProvidersState {
  providers: Array<{
    id: string;
    type: string;
    displayName: string;
    enabled: boolean;
    isDefault: boolean;
    config: Record<string, unknown>;
  }>;
}

interface ProvidersTestWindow extends Window {
  __providersCalls: ProvidersCall[];
}

const INITIAL_STATE: ProvidersState = {
  providers: [
    {
      id: '__builtin__',
      type: 'generic-http',
      displayName: 'Official (updates.sage.app)',
      enabled: true,
      isDefault: true,
      config: {
        manifestUrl: 'https://updates.sage.app/api/v1/updates/latest',
        channelMap: { stable: true, beta: true, alpha: true },
        requireArtifactSignature: true,
      },
    },
  ],
};

test.describe('Providers manager (hermetic)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const testWindow = window as unknown as ProvidersTestWindow;
      testWindow.__providersCalls = [];
      const state: ProvidersState = {
        providers: [
          {
            id: '__builtin__',
            type: 'generic-http',
            displayName: 'Official (updates.sage.app)',
            enabled: true,
            isDefault: true,
            config: {
              manifestUrl: 'https://updates.sage.app/api/v1/updates/latest',
              channelMap: { stable: true, beta: true, alpha: true },
              requireArtifactSignature: true,
            },
          },
        ],
      };
      // maskToken mirror of providerIpc.maskToken in main
      const maskToken = (cfg: Record<string, unknown>): Record<string, unknown> => {
        if ('token' in cfg && typeof cfg.token === 'string') {
          return { ...cfg, token: '***masked***' };
        }
        return cfg;
      };
      const summary = (p: (typeof state.providers)[number]) => ({
        id: p.id,
        type: p.type,
        displayName: p.displayName,
        enabled: p.enabled,
        isDefault: p.isDefault,
        createdAt: '',
        updatedAt: '',
        config: maskToken(p.config),
      });
      Object.defineProperty(window, 'electronAPI', {
        configurable: true,
        value: {
          invoke: async () => ({ status: 'ok' }),
          listen: async () => () => {},
          listLogFiles: async () => [],
          windowControls: {},
          providers: {
            list: async () => {
              testWindow.__providersCalls.push({ cmd: 'list' });
              return state.providers.map(summary);
            },
            get: async (id: string) => {
              const p = state.providers.find((x) => x.id === id);
              return p ? summary(p) : null;
            },
            add: async (
              payload: Omit<(typeof state.providers)[number], 'id'> & { id?: string },
            ) => {
              testWindow.__providersCalls.push({ cmd: 'add', payload });
              const id = payload.id ?? `usr_${Date.now()}`;
              const newProvider = {
                id,
                type: payload.type,
                displayName: payload.displayName,
                enabled: payload.enabled,
                isDefault: payload.isDefault ?? false,
                config: payload.config,
              };
              state.providers.push(newProvider);
              return summary(newProvider);
            },
            remove: async (id: string) => {
              testWindow.__providersCalls.push({ cmd: 'remove', payload: { id } });
              state.providers = state.providers.filter((p) => p.id !== id);
              return { status: 'ok' };
            },
            setDefault: async (id: string) => {
              testWindow.__providersCalls.push({ cmd: 'setDefault', payload: { id } });
              state.providers = state.providers.map((p) => ({
                ...p,
                isDefault: p.id === id,
              }));
              return { status: 'ok' };
            },
            test: async (id: string) => {
              testWindow.__providersCalls.push({ cmd: 'test', payload: { id } });
              return { ok: true, latencyMs: 42 };
            },
          },
        },
      });
    });
  });

  test('Settings → Providers tab 展示内置源', async ({ page }) => {
    await page.goto('/#/settings');
    await expect(page.getByText('设置')).toBeVisible();
    // Phase 3 T3.4: feature flag 全开 → Providers tab is visible by default.
    const providersTab = page.getByRole('button', { name: '更新源' });
    await expect(providersTab).toBeVisible();
    await providersTab.click();

    await expect(page.getByTestId('providers-manager')).toBeVisible();
    await expect(page.getByTestId('providers-current-default')).toContainText(
      'Official (updates.sage.app)',
    );
    // Built-in row present
    await expect(page.getByTestId('provider-row-__builtin__')).toBeVisible();
    // Add button visible
    await expect(page.getByTestId('providers-add-button')).toBeVisible();
  });

  test('Add GitHub provider → 行出现 + 设为默认 + 测试连接 + 删除', async ({
    page,
  }) => {
    await page.goto('/#/settings');
    await page.getByRole('button', { name: '更新源' }).click();
    await expect(page.getByTestId('providers-manager')).toBeVisible();

    // 1. Click Add → drives prompt() chain. Mock sequence:
    //    type=github, displayName='GH Test', owner='oneMuggle', repo='sage',
    //    token='', publicKey/manifestUrl/projectId/baseUrl skipped for github.
    const prompts: string[] = [
      '1', // type github
      'GH Test', // displayName
      'oneMuggle', // owner
      'sage', // repo
      '', // token (empty for public repo)
    ];
    let promptIdx = 0;
    page.on('dialog', async (dialog) => {
      if (dialog.type() === 'prompt') {
        const val = prompts[promptIdx++] ?? '';
        await dialog.accept(val);
      } else if (dialog.type() === 'confirm') {
        await dialog.accept();
      }
    });
    await page.getByTestId('providers-add-button').click();
    // Wait for refresh: list re-renders, the new row appears.
    const newRow = page.getByTestId(/^provider-row-usr_/);
    await expect(newRow).toBeVisible({ timeout: 5_000 });
    const newRowId = await newRow.getAttribute('data-testid');
    expect(newRowId).toMatch(/^provider-row-usr_/);

    // 2. Set as default
    const setDefaultBtn = page.getByTestId(
      newRowId!.replace('provider-row-', 'provider-set-default-'),
    );
    await setDefaultBtn.click();
    await expect(page.getByTestId('providers-current-default')).toContainText('GH Test');

    // 3. Test connection → ok alert
    page.once('dialog', async (dialog) => {
      expect(dialog.type()).toBe('alert');
      expect(dialog.message()).toContain('连接 OK');
      await dialog.accept();
    });
    await page
      .getByTestId(newRowId!.replace('provider-row-', 'provider-test-'))
      .click();

    // 4. Remove → confirm dialog → row disappears
    await page
      .getByTestId(newRowId!.replace('provider-row-', 'provider-remove-'))
      .click();
    await expect(newRow).toHaveCount(0);

    // Verify IPC sequence was driven through the mock:
    const calls = await page.evaluate(() => {
      const testWindow = window as unknown as ProvidersTestWindow;
      return testWindow.__providersCalls;
    });
    const cmds = calls.map((c) => c.cmd);
    expect(cmds).toContain('list');
    expect(cmds).toContain('add');
    expect(cmds).toContain('setDefault');
    expect(cmds).toContain('test');
    expect(cmds).toContain('remove');
    // ignore initial state: noinspection JSUnusedGlobalSymbols
    void INITIAL_STATE;
  });
});