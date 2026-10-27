/**
 * r81: API 客户端测试补齐——mcpClient / promptApi / agentsApi 的
 * 参数映射、返回值处理和错误传播。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../utils', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return {
    ...actual,
    handleApiError: (error: unknown) => error,
    withRetry: async (fn: () => Promise<unknown>) => fn(),
  };
});

import { agentsApi } from '../agentsApi';
import { mcpClient } from '../mcpClient';
import { promptApi } from '../promptApi';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('mcpClient', () => {
  it('status() invokes mcp_status and returns report', async () => {
    const report = { generated_at: 1, all_ready: true, degraded: false, failed_required: false, servers: [] };
    mockInvoke.mockResolvedValueOnce(report);
    const result = await mcpClient.status();
    expect(mockInvoke).toHaveBeenCalledWith('mcp_status', {});
    expect(result).toEqual(report);
  });

  it('listServers() invokes mcp_servers and returns servers array', async () => {
    mockInvoke.mockResolvedValueOnce({ servers: [{ name: 'srv' }] });
    const result = await mcpClient.listServers();
    expect(mockInvoke).toHaveBeenCalledWith('mcp_servers', {});
    expect(result).toEqual([{ name: 'srv' }]);
  });

  it('addServer() sends full config with snake_case keys', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await mcpClient.addServer({ name: 'srv', command: 'node', args: ['x.js'], required: true });
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_add',
      expect.objectContaining({ name: 'srv', command: 'node', args: ['x.js'], required: true }));
  });

  it('addServer() includes url and headers for HTTP transport', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await mcpClient.addServer({ name: 'remote', command: '', args: [], url: 'https://mcp.example/rpc', headers: { Authorization: 'Bearer k' }, required: false });
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_add',
      expect.objectContaining({ url: 'https://mcp.example/rpc', headers: { Authorization: 'Bearer k' } }));
  });

  it('updateServer() passes name + changes', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await mcpClient.updateServer('srv', { enabled: false });
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_update', expect.objectContaining({ name: 'srv', enabled: false }));
  });

  it('deleteServer() passes name', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true });
    await mcpClient.deleteServer('srv');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_delete', { name: 'srv' });
  });

  it('serverTools() invokes mcp_server_tools', async () => {
    mockInvoke.mockResolvedValueOnce({ server: 'srv', state: 'ready', tools: [], disabled_tools: [] });
    await mcpClient.serverTools('srv');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_tools', { name: 'srv' });
  });

  it('authorizeServer() invokes mcp_server_authorize', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, server: 'srv', token_type: 'Bearer', expires_at: 999 });
    await mcpClient.authorizeServer('srv');
    expect(mockInvoke).toHaveBeenCalledWith('mcp_server_authorize', { name: 'srv' });
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('MCP HTTP error'));
    await expect(mcpClient.status()).rejects.toThrow('MCP HTTP error');
  });
});

describe('promptApi', () => {
  it('list() invokes prompts_list and returns templates', async () => {
    const templates = [{ id: 'pt-1', name: 'tpl', description: '', content: '', created_at: 1, updated_at: 1 }];
    mockInvoke.mockResolvedValueOnce({ templates });
    const result = await promptApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('prompts_list');
    expect(result).toEqual(templates);
  });

  it('create() passes name/content/description', async () => {
    mockInvoke.mockResolvedValueOnce({ id: 'pt-1', name: 'n', description: '', content: 'c', created_at: 1, updated_at: 1 });
    await promptApi.create('n', 'c', 'd');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_create', expect.objectContaining({ name: 'n', content: 'c', description: 'd' }));
  });

  it('update() passes id and patch', async () => {
    mockInvoke.mockResolvedValueOnce({ id: 'pt-1', name: 'n2', description: '', content: 'c2', created_at: 1, updated_at: 2 });
    await promptApi.update('pt-1', { name: 'n2', content: 'c2' });
    expect(mockInvoke).toHaveBeenCalledWith('prompts_update', expect.objectContaining({ id: 'pt-1', name: 'n2', content: 'c2' }));
  });

  it('remove() passes id', async () => {
    mockInvoke.mockResolvedValueOnce({});
    await promptApi.remove('pt-1');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_delete', expect.objectContaining({ id: 'pt-1' }));
  });

  it('reorder() passes ordered ids', async () => {
    mockInvoke.mockResolvedValueOnce({});
    await promptApi.reorder(['b', 'a']);
    expect(mockInvoke).toHaveBeenCalledWith('prompts_reorder', expect.objectContaining({ orderedIds: ['b', 'a'] }));
  });

  it('exportTemplates() invokes prompts_export', async () => {
    mockInvoke.mockResolvedValueOnce({ app: 'sage', version: 1, templates: [] });
    await promptApi.exportTemplates();
    expect(mockInvoke).toHaveBeenCalledWith('prompts_export');
  });

  it('importTemplates() passes envelope and conflict mode', async () => {
    const envelope = { app: 'sage', version: 1, templates: [] };
    mockInvoke.mockResolvedValueOnce({ imported: 1, skipped: 0, failed: 0 });
    await promptApi.importTemplates(envelope, 'skip');
    expect(mockInvoke).toHaveBeenCalledWith('prompts_import', expect.objectContaining({ payload: expect.objectContaining({ conflict: 'skip' }) }));
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('后端未起'));
    await expect(promptApi.list()).rejects.toThrow('后端未起');
  });
});

describe('agentsApi', () => {
  it('list() invokes list_agents', async () => {
    const agents = [{ id: 'a1', name: 'researcher', enabled: true }];
    mockInvoke.mockResolvedValueOnce(agents);
    const result = await agentsApi.list();
    expect(mockInvoke).toHaveBeenCalledWith('list_agents');
    expect(result).toEqual(agents);
  });

  it('toggle() passes id and enabled via PATCH', async () => {
    const profile = { id: 'a1', name: 'researcher', enabled: false };
    mockInvoke.mockResolvedValueOnce(profile);
    const result = await agentsApi.toggle('a1', false);
    expect(mockInvoke).toHaveBeenCalledWith('toggle_agent', expect.objectContaining({ id: 'a1', enabled: false }));
    expect(result).toEqual(profile);
  });

  it('update() passes id and patch', async () => {
    const patch = { name: 'renamed', system_prompt: 'new prompt' };
    mockInvoke.mockResolvedValueOnce({ id: 'a1', ...patch });
    await agentsApi.update('a1', patch);
    expect(mockInvoke).toHaveBeenCalledWith('update_agent', expect.objectContaining({ id: 'a1', update: patch }));
  });

  it('create() passes full agent config', async () => {
    const agentConfig = { id: 'new-a', name: 'new-agent', system_prompt: 'sp', model: 'gpt-4o' };
    mockInvoke.mockResolvedValueOnce({ id: 'new-a' });
    await agentsApi.create(agentConfig);
    expect(mockInvoke).toHaveBeenCalledWith('create_agent', expect.objectContaining(agentConfig));
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('agent not found'));
    await expect(agentsApi.list()).rejects.toThrow('agent not found');
  });
});
