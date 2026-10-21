// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PluginEvent,
  PluginRecord,
  PluginRuntimeStatus,
} from '../../../shared/api/pluginClient';
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
  runtime: vi.fn(),
  startRuntime: vi.fn(),
  stopRuntime: vi.fn(),
  restartRuntime: vi.fn(),
  invokeRuntime: vi.fn(),
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
      runtime: (...args: unknown[]) => mocks.runtime(...args),
      startRuntime: (...args: unknown[]) => mocks.startRuntime(...args),
      stopRuntime: (...args: unknown[]) => mocks.stopRuntime(...args),
      restartRuntime: (...args: unknown[]) => mocks.restartRuntime(...args),
      invokeRuntime: (...args: unknown[]) => mocks.invokeRuntime(...args),
    },
  };
});

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: 'zh', setLocale: vi.fn() }),
}));

const pendingRuntime: PluginRuntimeStatus = {
  plugin_name: 'alpha',
  state: 'pending',
  running: false,
  pid: null,
  started_at: null,
  stopped_at: null,
  exit_code: null,
  restart_count: 0,
  capabilities: [],
  last_error: null,
  stderr_tail: '',
  limits: {
    startup_timeout_seconds: 10,
    request_timeout_seconds: 30,
    shutdown_timeout_seconds: 3,
    max_message_bytes: 1048576,
    memory_bytes: 536870912,
    cpu_seconds: 300,
    memory_limit_enforced: false,
    cpu_limit_enforced: false,
  },
};

const activeRuntime: PluginRuntimeStatus = {
  ...pendingRuntime,
  state: 'active',
  running: true,
  pid: 4242,
  started_at: 1760000000,
  capabilities: ['reader'],
  stderr_tail: 'worker ready',
  limits: { ...pendingRuntime.limits, memory_limit_enforced: true },
};

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
  runtime: pendingRuntime,
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
  runtime: { ...pendingRuntime, plugin_name: 'retired' },
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
    const activeAlpha = { ...alpha, status: 'enabled', runtime: activeRuntime };
    mocks.runtime.mockResolvedValue({ plugin: activeAlpha, runtime: activeRuntime });
    mocks.startRuntime.mockResolvedValue({ plugin: activeAlpha, runtime: activeRuntime });
    mocks.restartRuntime.mockResolvedValue({ plugin: activeAlpha, runtime: activeRuntime });
    mocks.stopRuntime.mockResolvedValue({
      plugin: { ...activeAlpha, runtime: { ...activeRuntime, state: 'disposed', running: false } },
      runtime: { ...activeRuntime, state: 'disposed', running: false },
    });
    mocks.invokeRuntime.mockResolvedValue({
      plugin_name: 'alpha',
      capability: 'reader',
      result: { content: 'hello' },
      runtime: activeRuntime,
    });
  });

  it('renders records, explicit runtime boundary, human permissions, and recent logs', async () => {
    render(<PluginsTab />);

    const card = await screen.findByTestId('plugin-card-alpha');
    expect(screen.getByText(/启用记录不会自动运行代码/)).toBeTruthy();
    expect(screen.getByText(/不是安全沙箱/)).toBeTruthy();
    expect(within(card).getByText('Alpha Plugin')).toBeTruthy();
    expect(screen.getByTestId('plugin-state-alpha').textContent).toBe('已安装');
    expect(screen.getByTestId('plugin-runtime-state-alpha').textContent).toContain('未启动');
    expect((screen.getByTestId('plugin-runtime-start-alpha') as HTMLButtonElement).disabled).toBe(
      true,
    );
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

  it('runtime controls call explicit start, restart, and stop endpoints', async () => {
    const enabledPending = { ...alpha, status: 'enabled' as const };
    const enabledActive = { ...enabledPending, runtime: activeRuntime };
    mocks.list.mockReset();
    mocks.list
      .mockResolvedValueOnce([enabledPending, retired])
      .mockResolvedValue([enabledActive, retired]);

    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');
    expect((screen.getByTestId('plugin-runtime-start-alpha') as HTMLButtonElement).disabled).toBe(
      false,
    );

    fireEvent.click(screen.getByTestId('plugin-runtime-start-alpha'));
    await waitFor(() => expect(mocks.startRuntime).toHaveBeenCalledWith('alpha'));
    await waitFor(() =>
      expect(screen.getByTestId('plugin-runtime-state-alpha').textContent).toContain('运行中'),
    );

    fireEvent.click(screen.getByTestId('plugin-runtime-restart-alpha'));
    await waitFor(() => expect(mocks.restartRuntime).toHaveBeenCalledWith('alpha'));

    fireEvent.click(screen.getByTestId('plugin-runtime-stop-alpha'));
    await waitFor(() => expect(mocks.stopRuntime).toHaveBeenCalledWith('alpha'));
  });

  it('runtime panel invokes a loaded tool and rejects non-object arguments locally', async () => {
    const enabledActive = { ...alpha, status: 'enabled' as const, runtime: activeRuntime };
    mocks.list.mockResolvedValue([enabledActive, retired]);

    render(<PluginsTab />);
    await screen.findByTestId('plugin-card-alpha');
    fireEvent.click(screen.getByTestId('plugin-details-alpha'));
    await screen.findByTestId('plugin-runtime-panel-alpha');
    expect(screen.getByTestId('plugin-runtime-stderr-alpha').textContent).toContain('worker ready');

    fireEvent.change(screen.getByTestId('plugin-invoke-args-alpha'), {
      target: { value: '{"path":"a.txt"}' },
    });
    fireEvent.click(screen.getByTestId('plugin-invoke-alpha'));

    await waitFor(() =>
      expect(mocks.invokeRuntime).toHaveBeenCalledWith('alpha', 'reader', { path: 'a.txt' }),
    );
    expect(await screen.findByTestId('plugin-invoke-result-alpha')).toBeTruthy();
    expect(screen.getByTestId('plugin-invoke-result-alpha').textContent).toContain('hello');

    fireEvent.change(screen.getByTestId('plugin-invoke-args-alpha'), { target: { value: '[]' } });
    fireEvent.click(screen.getByTestId('plugin-invoke-alpha'));
    expect(await screen.findByText('参数必须是 JSON 对象。')).toBeTruthy();
    expect(mocks.invokeRuntime).toHaveBeenCalledTimes(1);
  });

  it('shows load errors without hiding the boundary note', async () => {
    mocks.list.mockRejectedValue(new Error('backend offline'));

    render(<PluginsTab />);

    expect(await screen.findByText('backend offline')).toBeTruthy();
    expect(screen.getByText(/启用记录不会自动运行代码/)).toBeTruthy();
  });
});
