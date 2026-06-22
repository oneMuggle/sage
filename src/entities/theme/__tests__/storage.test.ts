import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGet = vi.fn();
const mockSet = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: (...args: unknown[]) => mockGet(...args),
    setPreference: (...args: unknown[]) => mockSet(...args),
  },
}));

import { loadTheme, saveTheme } from '../storage';

const CACHE_KEY = 'sage-theme';

describe('theme storage', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGet.mockReset();
    mockSet.mockReset();
  });

  it('loadTheme 后端命中时返回 backend 值', async () => {
    mockGet.mockResolvedValue('dark');
    const r = await loadTheme();
    expect(r).toBe('dark');
  });

  it('loadTheme 后端无值时回退 localStorage', async () => {
    mockGet.mockResolvedValue(null);
    localStorage.setItem(CACHE_KEY, 'light');
    const r = await loadTheme();
    expect(r).toBe('light');
  });

  it('loadTheme 全部为空时返回 null', async () => {
    mockGet.mockResolvedValue(null);
    expect(await loadTheme()).toBeNull();
  });

  it('saveTheme 同步写 localStorage + 异步写后端', async () => {
    await saveTheme('dark');
    expect(localStorage.getItem(CACHE_KEY)).toBe('dark');
    expect(mockSet).toHaveBeenCalledWith('theme_mode', 'dark', 'ui');
  });

  it('saveTheme 接受 system 模式', async () => {
    await saveTheme('system');
    expect(localStorage.getItem(CACHE_KEY)).toBe('system');
  });
});
