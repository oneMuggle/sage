/**
 * r90: mcpClient 单元测试——状态/服务器 CRUD/工具清单/OAuth 授权 + 名称正则。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { mcpClient, MCP_NAME_REGEX } from '../mcpClient';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('mcpClient', () => {
  it('status() invokes mcp_status with empty payload', async () => {
    const report = { generated_at: 1, all_ready: true, degraded: false, failed_required: false, servers: [] };
    mockInvoke.mockResolvedValueOnce(report);
    const r = await mcpClient.status();
    expect(mockInvoke).toHaveBeenCalledWith('mcp_status', {});
    expect(r.all_ready).toBe(true);
  });

  it('listServers() unwraps servers array', async () => {
    const cfg = {
      name: 'fs', command: 'python', url: null, args: [], env: {},
      enabled: true, required: false, timeout_seconds: 30, builtin: false,
    };
    mockInvoke.mockResolvedValueOnce({ servers: [cfg] });
    const r = await mcpClient.listServers();
    expect(mockInvoke).toHaveBeenCalledWith('mcp_servers', {});
    expect(r[0].name).toBe('fs');
  });

  it('addServer() sends snake_case rawBody payload with defaults', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, name: 'fs', state: 'discovering' });
    const r = await mcpClient.addServer({
      name: 'fs', command: 'python', url: null, args: ['-m', 'server'], required: false,
    });
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_add', {
      name: 'fs',
      command: 'python',
      args: ['-m', 'server'],
      env: {},
      enabled: true,
      required: false,
      timeout_seconds: 30,
    });
    expect(r.ok).toBe(true);
  });

  it('addServer() includes url/headers only when provided', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, name: 'http-mcp', state: 'discovering' });
    await mcpClient.addServer({
      name: 'http-mcp', command: '', url: 'https://mcp.example/v1',
      headers: { Authorization: 'Bearer x' }, args: [], required: true,
    });
    const payload = mockInvoke.mock.calls[0][1];
    expect(payload.url).toBe('https://mcp.example/v1');
    expect(payload.headers).toEqual({ Authorization: 'Bearer x' });
    expect(payload.required).toBe(true);
  });

  it('updateServer() maps camelCase changes to snake_case', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, name: 'fs', state: 'ready' });
    await mcpClient.updateServer('fs', {
      enabled: false, timeoutSeconds: 60, disabledTools: ['t1', 't2'],
    });
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_update', {
      name: 'fs',
      enabled: false,
      timeout_seconds: 60,
      disabled_tools: ['t1', 't2'],
    });
  });

  it('serverTools() passes name', async () => {
    mockInvoke.mockResolvedValueOnce({
      server: 'fs', state: 'ready', tools: [{ name: 'search', description: 'd' }],
      disabled_tools: [],
    });
    const r = await mcpClient.serverTools('fs');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_tools', { name: 'fs' });
    expect(r.tools[0].name).toBe('search');
  });

  it('authorizeServer() passes name (long OAuth request)', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, server: 'http-mcp', token_type: 'bearer', expires_at: 99 });
    const r = await mcpClient.authorizeServer('http-mcp');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_authorize', { name: 'http-mcp' });
    expect(r.token_type).toBe('bearer');
  });

  it('deleteServer() passes name', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, name: 'fs' });
    await mcpClient.deleteServer('fs');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_delete', { name: 'fs' });
  });
});

describe('MCP_NAME_REGEX', () => {
  it('accepts lowercase / digits / underscore / hyphen', () => {
    expect(MCP_NAME_REGEX.test('fs')).toBe(true);
    expect(MCP_NAME_REGEX.test('my-server_2')).toBe(true);
    expect(MCP_NAME_REGEX.test('a')).toBe(true);
    expect(MCP_NAME_REGEX.test('a'.repeat(64))).toBe(true);
  });

  it('rejects uppercase, spaces, special chars and empty', () => {
    expect(MCP_NAME_REGEX.test('FS')).toBe(false);
    expect(MCP_NAME_REGEX.test('my server')).toBe(false);
    expect(MCP_NAME_REGEX.test('')).toBe(false);
    expect(MCP_NAME_REGEX.test('服')).toBe(false);
  });

  it('rejects names longer than 64 chars', () => {
    expect(MCP_NAME_REGEX.test('a'.repeat(65))).toBe(false);
  });
});
