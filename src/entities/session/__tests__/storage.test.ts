import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGet = vi.fn();
const mockSet = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: (...args: unknown[]) => mockGet(...args),
    setPreference: (...args: unknown[]) => mockSet(...args),
  },
}));

import { loadCurrentSessionId, saveCurrentSessionId } from '../storage';

const CACHE_KEY = 'sage-current-session-id';

describe('session storage', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGet.mockReset();
    mockSet.mockReset();
  });

  it('loadCurrentSessionId 后端命中时返回 backend 值', async () => {
    mockGet.mockResolvedValue('abc-123');
    const r = await loadCurrentSessionId();
    expect(r).toBe('abc-123');
  });

  it('loadCurrentSessionId 后端无值时回退 localStorage', async () => {
    mockGet.mockResolvedValue(null);
    localStorage.setItem(CACHE_KEY, 'local-456');
    const r = await loadCurrentSessionId();
    expect(r).toBe('local-456');
  });

  it('loadCurrentSessionId 全空时返回 null', async () => {
    mockGet.mockResolvedValue(null);
    expect(await loadCurrentSessionId()).toBeNull();
  });

  it('saveCurrentSessionId 写 localStorage + 后端', async () => {
    await saveCurrentSessionId('xyz-789');
    expect(localStorage.getItem(CACHE_KEY)).toBe('xyz-789');
    expect(mockSet).toHaveBeenCalledWith('current_session_id', 'xyz-789', 'session');
  });

  it('saveCurrentSessionId(null) 清空 localStorage', async () => {
    localStorage.setItem(CACHE_KEY, 'old');
    await saveCurrentSessionId(null);
    expect(localStorage.getItem(CACHE_KEY)).toBeNull();
  });
});
