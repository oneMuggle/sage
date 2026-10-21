/** R82：pluginClient 请求契约与 409 权限确认解析测试。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const backendRequest = vi.fn();

vi.mock('../backendRequest', () => ({
  backendRequest: (...args: unknown[]) => backendRequest(...args),
}));

import {
  describePermission,
  extractManifestPermissions,
  parsePluginConfirmationError,
  pluginClient,
  PluginPermissionConfirmationRequiredError,
} from '../pluginClient';

const plugin = {
  name: 'alpha',
  version: '1.0.0',
  status: 'installed',
  install_path: '/plugins/alpha',
  config: {},
  manifest: {},
  display_name: 'Alpha',
  description: '',
  permissions: [],
  by_capability: [],
  error_message: null,
  created_at: '2026-10-21T00:00:00Z',
  updated_at: '2026-10-21T00:00:00Z',
  installed_at: '2026-10-21T00:00:00Z',
};

beforeEach(() => {
  backendRequest.mockReset();
});

describe('pluginClient', () => {
  it('list() unwraps plugins and encodes the status filter', async () => {
    backendRequest.mockResolvedValueOnce({ plugins: [plugin] });

    await expect(pluginClient.list('enabled')).resolves.toEqual([plugin]);
    expect(backendRequest).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/plugins?status=enabled',
    });
  });

  it('get() encodes plugin names', async () => {
    backendRequest.mockResolvedValueOnce({ plugin });

    await pluginClient.get('alpha/beta');
    expect(backendRequest).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/plugins/alpha%2Fbeta',
    });
  });

  it('install() sends the snake_case backend contract', async () => {
    backendRequest.mockResolvedValueOnce({ plugin });
    const manifest = { name: 'alpha', version: '1.0.0' };

    await expect(
      pluginClient.install({ manifest, installPath: '/plugins/alpha', confirmPermissions: true }),
    ).resolves.toEqual(plugin);
    expect(backendRequest).toHaveBeenCalledWith({
      method: 'POST',
      path: '/api/v1/plugins',
      body: {
        manifest,
        install_path: '/plugins/alpha',
        confirm_permissions: true,
      },
    });
  });

  it('install() converts a relayed 409 body into a typed confirmation error', async () => {
    const payload = {
      ok: false,
      error: 'permissions_confirmation_required',
      detail: 'confirm first',
      plugin: 'alpha',
      permissions: ['file:read'],
      by_capability: [
        {
          capability: 'reader',
          type: 'tool',
          description: 'Reads',
          entry_point: 'reader:run',
          permissions: ['file:read'],
        },
      ],
    };
    backendRequest.mockRejectedValueOnce(
      new Error(`Backend request failed: 409 ${JSON.stringify(payload)}`),
    );

    const error = await pluginClient
      .install({ manifest: {}, installPath: '/plugins/alpha' })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(PluginPermissionConfirmationRequiredError);
    expect((error as PluginPermissionConfirmationRequiredError).payload).toEqual(payload);
  });

  it('lifecycle actions use the expected methods and paths', async () => {
    backendRequest.mockResolvedValue({ plugin });

    await pluginClient.enable('alpha');
    await pluginClient.disable('alpha');
    await pluginClient.restore('alpha');
    await pluginClient.uninstall('alpha');

    expect(backendRequest.mock.calls.map(([request]) => request)).toEqual([
      { method: 'POST', path: '/api/v1/plugins/alpha/enable' },
      { method: 'POST', path: '/api/v1/plugins/alpha/disable' },
      { method: 'POST', path: '/api/v1/plugins/alpha/restore' },
      { method: 'DELETE', path: '/api/v1/plugins/alpha' },
    ]);
  });

  it('updateConfig(), permissions(), and logs() call their endpoints', async () => {
    backendRequest
      .mockResolvedValueOnce({ plugin })
      .mockResolvedValueOnce({ plugin: 'alpha', permissions: [], by_capability: [] })
      .mockResolvedValueOnce({ logs: [] })
      .mockResolvedValueOnce({ logs: [] });

    await pluginClient.updateConfig('alpha', { mode: 'strict' });
    await pluginClient.permissions('alpha');
    await pluginClient.logs('alpha', 5);
    await pluginClient.logs(undefined, 7);

    expect(backendRequest.mock.calls.map(([request]) => request)).toEqual([
      {
        method: 'PATCH',
        path: '/api/v1/plugins/alpha/config',
        body: { config: { mode: 'strict' } },
      },
      { method: 'GET', path: '/api/v1/plugins/alpha/permissions' },
      { method: 'GET', path: '/api/v1/plugins/alpha/logs?limit=5' },
      { method: 'GET', path: '/api/v1/plugins/logs?limit=7' },
    ]);
  });
});

describe('plugin permission helpers', () => {
  it('describePermission translates known permissions and preserves unknown ones', () => {
    expect(describePermission('file:read')).toBe('读取文件');
    expect(describePermission('network:write', 'en')).toBe('Send network requests');
    expect(describePermission('custom:teleport')).toBe('custom:teleport');
  });

  it('extractManifestPermissions deduplicates while preserving order', () => {
    expect(
      extractManifestPermissions({
        capabilities: [
          { permissions: ['file:read', 'network:write'] },
          { permissions: ['network:write', 'shell:execute'] },
          { permissions: 'not-an-array' },
        ],
      }),
    ).toEqual(['file:read', 'network:write', 'shell:execute']);
    expect(extractManifestPermissions(null)).toEqual([]);
  });

  it('parsePluginConfirmationError ignores unrelated or malformed errors', () => {
    expect(parsePluginConfirmationError(new Error('plain failure'))).toBeNull();
    expect(parsePluginConfirmationError(new Error('409 {not json'))).toBeNull();
    expect(parsePluginConfirmationError(new Error('409 {"error":"other"}'))).toBeNull();
  });
});
