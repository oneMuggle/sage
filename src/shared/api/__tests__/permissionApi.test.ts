/**
 * r87: permissionApi 单元测试——preset 读写 + 会话自动放行审计。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock('../demoFlag', () => ({ isDemoMode: () => false }));

vi.mock('../utils', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  return { ...actual, handleApiError: (e: unknown) => e };
});

import { permissionApi } from '../permissionApi';

beforeEach(() => { mockInvoke.mockReset(); });

describe('permissionApi', () => {
  it('getPreset() returns parsed preset state', async () => {
    mockInvoke.mockResolvedValueOnce({ preset: 'auto', mode: 'full_access', custom: true });
    const r = await permissionApi.getPreset();
    expect(mockInvoke).toHaveBeenCalledWith('permissions_get_preset', {});
    expect(r.preset).toBe('auto');
    expect(r.mode).toBe('full_access');
    expect(r.custom).toBe(true);
  });

  it('getPreset() falls back to standard on invalid preset', async () => {
    mockInvoke.mockResolvedValueOnce({ preset: 'bogus', mode: 'workspace_write' });
    const r = await permissionApi.getPreset();
    expect(r.preset).toBe('standard');
  });

  it('setPreset() invokes permissions_set_preset', async () => {
    await permissionApi.setPreset('auto');
    expect(mockInvoke).toHaveBeenCalledWith('permissions_set_preset', { preset: 'auto' });
  });

  it('propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('backend down'));
    await expect(permissionApi.getPreset()).rejects.toThrow('backend down');
  });

  it('listRules() parses rules and drops invalid entries', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      rules: [
        { tool_pattern: 'bash', decision: 'deny' },
        { tool_pattern: 'plugin__demo__*', decision: 'allow' },
        { tool_pattern: '', decision: 'allow' },
        { tool_pattern: 'write_file', decision: 'bogus' },
        'junk',
        { decision: 'ask' },
      ],
    });
    const rules = await permissionApi.listRules();
    expect(mockInvoke).toHaveBeenCalledWith('permissions_list_rules', {});
    expect(rules).toEqual([
      { tool_pattern: 'bash', decision: 'deny', plugin_name: null, plugin_status: null },
      { tool_pattern: 'plugin__demo__*', decision: 'allow', plugin_name: null, plugin_status: null },
    ]);
  });

  it('listRules() carries plugin attribution and nulls bad types', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      rules: [
        {
          tool_pattern: 'plugin__demo__*',
          decision: 'deny',
          plugin_name: 'demo',
          plugin_status: 'uninstalled',
        },
        {
          tool_pattern: 'plugin__ghost__*',
          decision: 'ask',
          plugin_name: 42,
          plugin_status: 'missing',
        },
      ],
    });
    const rules = await permissionApi.listRules();
    expect(rules).toEqual([
      {
        tool_pattern: 'plugin__demo__*',
        decision: 'deny',
        plugin_name: 'demo',
        plugin_status: 'uninstalled',
      },
      {
        tool_pattern: 'plugin__ghost__*',
        decision: 'ask',
        plugin_name: null,
        plugin_status: 'missing',
      },
    ]);
  });

  it('listRules() returns [] on malformed payload', async () => {
    mockInvoke.mockResolvedValueOnce(null);
    await expect(permissionApi.listRules()).resolves.toEqual([]);
  });

  it('deleteRule() invokes permissions_delete_rule and returns updated list', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      rules: [{ tool_pattern: 'write_file', decision: 'ask' }],
    });
    const rules = await permissionApi.deleteRule({ tool_pattern: 'bash', decision: 'deny' });
    expect(mockInvoke).toHaveBeenCalledWith('permissions_delete_rule', {
      toolPattern: 'bash',
      decision: 'deny',
    });
    expect(rules).toEqual([
      { tool_pattern: 'write_file', decision: 'ask', plugin_name: null, plugin_status: null },
    ]);
  });

  it('deleteRule() propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('backend down'));
    await expect(
      permissionApi.deleteRule({ tool_pattern: 'bash', decision: 'deny' }),
    ).rejects.toThrow('backend down');
  });

  it('clearRules() invokes permissions_clear_rules and returns updated list', async () => {
    mockInvoke.mockResolvedValueOnce({ ok: true, rules: [] });
    const rules = await permissionApi.clearRules();
    expect(mockInvoke).toHaveBeenCalledWith('permissions_clear_rules', {});
    expect(rules).toEqual([]);
  });

  it('clearRules() propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('backend down'));
    await expect(permissionApi.clearRules()).rejects.toThrow('backend down');
  });

  it('deleteRulesByPlugin() invokes with pluginName only and returns updated list', async () => {
    mockInvoke.mockResolvedValueOnce({
      ok: true,
      removed: 2,
      rules: [{ tool_pattern: 'bash', decision: 'allow' }],
    });
    const rules = await permissionApi.deleteRulesByPlugin('demo');
    expect(mockInvoke).toHaveBeenCalledWith('permissions_delete_rules_by_plugin', {
      pluginName: 'demo',
    });
    expect(rules).toEqual([
      { tool_pattern: 'bash', decision: 'allow', plugin_name: null, plugin_status: null },
    ]);
  });

  it('deleteRulesByPlugin() propagates invoke errors', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('plugin not found'));
    await expect(permissionApi.deleteRulesByPlugin('ghost')).rejects.toThrow(
      'plugin not found',
    );
  });
});
