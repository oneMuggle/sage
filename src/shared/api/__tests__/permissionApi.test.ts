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
});
