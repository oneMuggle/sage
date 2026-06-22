import { beforeEach, describe, expect, it, vi } from 'vitest';

// 桩化 invoke
const mockInvoke = vi.fn();
vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { settingsClient, LOAD_TIMEOUT_MS } from '../settingsClient';

describe('settingsClient', () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it('getSettings 成功时返回数据', async () => {
    mockInvoke.mockResolvedValue({ data: { maxContext: 4096 } });
    const result = await settingsClient.getSettings();
    expect(result).toEqual({ maxContext: 4096 });
    expect(mockInvoke).toHaveBeenCalledWith('get_settings', {});
  });

  it('getSettings 失败时返回 null 不抛', async () => {
    mockInvoke.mockRejectedValue(new Error('IPC fail'));
    const result = await settingsClient.getSettings();
    expect(result).toBeNull();
  });

  it(
    'getSettings 超时时返回 null',
    async () => {
      mockInvoke.mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, LOAD_TIMEOUT_MS + 1000)),
      );
      const result = await settingsClient.getSettings();
      expect(result).toBeNull();
    },
    LOAD_TIMEOUT_MS + 2000,
  );

  it('setSettings 失败时静默（不抛）', async () => {
    mockInvoke.mockRejectedValue(new Error('IPC fail'));
    await expect(settingsClient.setSettings({ maxContext: 8000 })).resolves.toBeUndefined();
  });

  it('getPreference 走 get_preference cmd', async () => {
    mockInvoke.mockResolvedValue({ value: 'dark' });
    const result = await settingsClient.getPreference('theme_mode');
    expect(result).toBe('dark');
    expect(mockInvoke).toHaveBeenCalledWith('get_preference', { key: 'theme_mode' });
  });

  it('setPreference 走 set_preference cmd', async () => {
    mockInvoke.mockResolvedValue({});
    await settingsClient.setPreference('theme_mode', 'light');
    expect(mockInvoke).toHaveBeenCalledWith('set_preference', {
      key: 'theme_mode',
      value: 'light',
      value_type: 'string',
      category: 'ui',
    });
  });
});
