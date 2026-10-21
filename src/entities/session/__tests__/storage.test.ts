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
import { formatCurrentSessionStorageJson, formatCurrentSessionStorageSummary } from '../storage';

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

  it('formats current session storage summary and JSON (Phase P108)', () => {
    localStorage.setItem(CACHE_KEY, 'cached-01');
    expect(formatCurrentSessionStorageSummary('active-01')).toBe(
      'sage-current-session-id · current=active-01 · cached=cached-01',
    );
    expect(formatCurrentSessionStorageSummary(null)).toBe(
      'sage-current-session-id · current=none · cached=cached-01',
    );
    const parsed = JSON.parse(formatCurrentSessionStorageJson('active-01'));
    expect(parsed).toEqual({
      cacheKey: 'sage-current-session-id',
      currentSessionId: 'active-01',
      cachedSessionId: 'cached-01',
    });
  });
});
