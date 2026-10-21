// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PluginEvent, PluginRecord } from '../../../shared/api/pluginClient';
import { PluginsTab } from '../PluginsTab';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  install: vi.fn(),
  enable: vi.fn(),
  disable: vi.fn(),
  restore: vi.fn(),
  uninstall: vi.fn(),
  updateConfig: vi.fn(),
  permissions: vi.fn(),
  logs: vi.fn(),
}));

vi.mock('../../../shared/api/pluginClient', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/pluginClient')>(
    '../../../shared/api/pluginClient',
  );
  return {
    ...actual,
    pluginClient: {
      list: (...args: unknown[]) => mocks.list(...args),
      get: (...args: unknown[]) => mocks.get(...args),
      install: (...args: unknown[]) => mocks.install(...args),
      enable: (...args: unknown[]) => mocks.enable(...args),
      disable: (...args: unknown[]) => mocks.disable(...args),
      restore: (...args: unknown[]) => mocks.restore(...args),
      uninstall: (...args: unknown[]) => mocks.uninstall(...args),
      updateConfig: (...args: unknown[]) => mocks.updateConfig(...args),
      permissions: (...args: unknown[]) => mocks.permissions(...args),
      logs: (...args: unknown[]) => mocks.logs(...args),
    },
  };
});

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

const alpha: PluginRecord = {
  name: 'alpha',
  version: '1.2.3',
  status: 'installed',
  install_path: '/plugins/alpha',
  config: { mode: 'safe' },
  manifest: {
    name: 'alpha',
    version: '1.2.3',
    metadata: { display_name: 'Alpha Plugin', description: 'Alpha description' },
    capabilities: [
      {
        type: 'tool',
        name: 'reader',
        description: 'Reads files',
        entry_point: 'reader:run',
        permissions: ['file:read'],
      },
    ],
  },
  display_name: 'Alpha Plugin',
  description: 'Alpha description',
  permissions: ['file:read'],
  by_capability: [
    {
      capability: 'reader',
      type: 'tool',
      description: 'Reads files',
      entry_point: 'reader:run',
      permissions: ['file:read'],
    },
  ],
  error_message: null,
  created_at: '2026-10-21T00:00:00Z',
  updated_at: '2026-10-21T01:00:00Z',
  installed_at: '2026-10-21T00:00:00Z',
};

const retired: PluginRecord = {
  ...alpha,
  name: 'retired',
  status: 'uninstalled',
  install_path: '/plugins/retired',
  config: {},
  manifest: { name: 'retired', capabilities: [] },
  display_name: 'Retired Plugin',
  description: 'Old plugin',
  permissions: [],
  by_capability: [],
};

const alphaLog: PluginEvent = {
  id: 2,
  plugin_name: 'alpha',
  event: 'installed',
  detail: 'installed from test',
  created_at: '2026-10-21T01:00:00Z',
};

describe('PluginsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue([alpha, retired]);
    mocks.logs.mockImplementation(async (name?: string) => (name ? [alphaLog] : [alphaLog]));
    mocks.enable.mockResolvedValue({ ...alpha, status: 'enabled' });
    mocks.disable.mockResolvedValue({ ...alpha, status: 'disabled' });
    mocks.restore.mockResolvedValue({ ...retired, status: 'installed' });
    mocks.uninstall.mockResolvedValue({ ...alpha, status: 'uninstalled' });
    mocks.updateConfig.mockResolvedValue({ ...alpha, config: { mode: 'strict' } });
    mocks.install.mockResolvedValue(alpha);
  });

  it('renders records, honest R83 boundary, human permissions, and recent logs', async () => {
    render(<PluginsTab />);

    const card = await screen.findByTestId('plugin-card-alpha');
    expect(screen.getByText(/插件代码加载与托管将在 R83 接入/)).toBeTruthy();
    expect(within(card).getByText('Alpha Plugin')).toBeTruthy();
    expect(screen.getByTestId('plugin-state-alpha').textContent).toBe('已安装');
    expect(within(card).getByText('读取文件')).toBeTruthy();
    expect(within(card).getByText('file:read')).toBeTruthy();
    expect(screen.getByTestId('plugin-recent-logs').textContent).toContain('alpha');
    expect(screen.getByTestId('plugin-count').textContent).toContain('2');
  });

  it('toggle enables an installed plugin record', async () => {
    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');

    fireEvent.click(screen.getByTestId('plugin-toggle-alpha'));

    await waitFor(() => expect(mocks.enable).toHaveBeenCalledWith('alpha'));
  });

  it('details load plugin logs and save JSON config', async () => {
    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');

    fireEvent.click(screen.getByTestId('plugin-details-alpha'));
    await screen.findByTestId('plugin-detail-alpha');
    await waitFor(() => expect(mocks.logs).toHaveBeenCalledWith('alpha', 50));
    expect(screen.getByTestId('plugin-logs-alpha').textContent).toContain('installed from test');

    fireEvent.change(screen.getByTestId('plugin-config-alpha'), {
      target: { value: '{"mode":"strict"}' },
    });
    fireEvent.click(screen.getByTestId('plugin-save-config-alpha'));

    await waitFor(() =>
      expect(mocks.updateConfig).toHaveBeenCalledWith('alpha', { mode: 'strict' }),
    );
  });

  it('rejects non-object JSON config before calling the API', async () => {
    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');
    fireEvent.click(screen.getByTestId('plugin-details-alpha'));
    await screen.findByTestId('plugin-detail-alpha');

    fireEvent.change(screen.getByTestId('plugin-config-alpha'), { target: { value: '[]' } });
    fireEvent.click(screen.getByTestId('plugin-save-config-alpha'));

    expect(await screen.findByText('配置必须是 JSON 对象。')).toBeTruthy();
    expect(mocks.updateConfig).not.toHaveBeenCalled();
  });

  it('uninstall and restore actions call the matching endpoints', async () => {
    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');

    fireEvent.click(screen.getByTestId('plugin-uninstall-alpha'));
    await waitFor(() => expect(mocks.uninstall).toHaveBeenCalledWith('alpha'));

    fireEvent.click(screen.getByTestId('plugin-restore-retired'));
    await waitFor(() => expect(mocks.restore).toHaveBeenCalledWith('retired'));
  });

  it('backend 409 opens a per-permission confirmation flow before retrying', async () => {
    const payload = {
      ok: false,
      error: 'permissions_confirmation_required',
      detail: 'confirm first',
      plugin: 'example-plugin',
      permissions: ['file:read'],
      by_capability: [
        {
          capability: 'example-tool',
          type: 'tool',
          description: 'Example',
          entry_point: 'tools.example',
          permissions: ['file:read'],
        },
      ],
    };
    mocks.install
      .mockRejectedValueOnce(new Error(`Backend request failed: 409 ${JSON.stringify(payload)}`))
      .mockResolvedValueOnce({ ...alpha, name: 'example-plugin' });

    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');
    fireEvent.change(screen.getByTestId('plugin-install-path'), {
      target: { value: '/plugins/example-plugin' },
    });

    expect(screen.getByTestId('plugin-permission-preview')).toBeTruthy();
    fireEvent.click(screen.getByTestId('plugin-install-submit'));

    const confirmation = await screen.findByTestId('plugin-confirmation-required');
    expect(within(confirmation).getByText('example-tool')).toBeTruthy();
    expect(mocks.install.mock.calls[0][0].confirmPermissions).toBe(false);
    expect((screen.getByTestId('plugin-install-submit') as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByTestId('plugin-confirm-permissions'));
    fireEvent.click(screen.getByTestId('plugin-install-submit'));

    await waitFor(() => expect(mocks.install).toHaveBeenCalledTimes(2));
    expect(mocks.install.mock.calls[1][0].confirmPermissions).toBe(true);
    expect(mocks.install.mock.calls[1][0].installPath).toBe('/plugins/example-plugin');
  });

  it('shows load errors without hiding the boundary note', async () => {
    mocks.list.mockRejectedValue(new Error('backend offline'));

    render(<PluginsTab />);

    expect(await screen.findByText('backend offline')).toBeTruthy();
    expect(screen.getByText(/R82 只管理生命周期记录/)).toBeTruthy();
  });
});
