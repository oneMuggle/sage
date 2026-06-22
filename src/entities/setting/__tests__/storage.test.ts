import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockGetSettings = vi.fn();
const mockSetSettings = vi.fn();
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getSettings: (...args: unknown[]) => mockGetSettings(...args),
    setSettings: (...args: unknown[]) => mockSetSettings(...args),
  },
}));

import { loadSettings, saveSettings, resetSettings } from '../storage';
import { DEFAULT_SETTINGS, SETTINGS_STORAGE_KEY } from '../types';

const CACHE_KEY = SETTINGS_STORAGE_KEY; // 'sage-settings'
const MIGRATION_MARKER = 'sage-settings.migrated_to_backend';

describe('settings storage (async)', () => {
  beforeEach(() => {
    localStorage.clear();
    mockGetSettings.mockReset();
    mockSetSettings.mockReset();
  });

  describe('loadSettings', () => {
    it('后端命中时返回 backend 数据并写 local cache', async () => {
      const remoteData = { ...DEFAULT_SETTINGS, maxContext: 8000 };
      mockGetSettings.mockResolvedValue(remoteData);
      const r = await loadSettings();
      expect(r.maxContext).toBe(8000);
      expect(JSON.parse(localStorage.getItem(CACHE_KEY)!).maxContext).toBe(8000);
    });

    it('后端无值且 localStorage 有值时回退 local', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, temperature: 0.3 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.temperature).toBe(0.3);
    });

    it('都为空时返回 DEFAULT_SETTINGS', async () => {
      mockGetSettings.mockResolvedValue(null);
      const r = await loadSettings();
      expect(r).toEqual(DEFAULT_SETTINGS);
    });

    it('后端失败时降级 localStorage', async () => {
      mockGetSettings.mockResolvedValue(null);
      const local = { ...DEFAULT_SETTINGS, compactMode: true };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      const r = await loadSettings();
      expect(r.compactMode).toBe(true);
    });
  });

  describe('自动迁移', () => {
    it('首次后端命中 + localStorage 有值 + 未标记迁移 → 自动上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce(null); // 第一次：后端无
      mockSetSettings.mockResolvedValueOnce(undefined);

      await loadSettings();

      expect(mockSetSettings).toHaveBeenCalledWith(expect.objectContaining({ maxContext: 9999 }));
      expect(localStorage.getItem(MIGRATION_MARKER)).toBeTruthy();
    });

    it('已标记迁移时不重复上传', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      localStorage.setItem(MIGRATION_MARKER, '2026-06-22T00:00:00.000Z');
      mockGetSettings.mockResolvedValueOnce(null);

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });

    it('后端已有数据时不触发迁移', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });

  describe('saveSettings', () => {
    it('同步写 localStorage', async () => {
      await saveSettings({ maxContext: 16000 });
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached.maxContext).toBe(16000);
    });

    it('异步调 setSettings', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await saveSettings({ maxContext: 16000 });
      expect(mockSetSettings).toHaveBeenCalledWith({ maxContext: 16000 });
    });
  });

  describe('resetSettings', () => {
    it('重置为 DEFAULT_SETTINGS 并写 local + 后端', async () => {
      mockSetSettings.mockResolvedValueOnce(undefined);
      await resetSettings();
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY)!);
      expect(cached).toEqual(DEFAULT_SETTINGS);
      expect(mockSetSettings).toHaveBeenCalled();
    });
  });

  describe('7 天保留清理', () => {
    it('迁移标记 >7 天时清理 localStorage 冗余数据', async () => {
      const local = { ...DEFAULT_SETTINGS, maxContext: 9999 };
      localStorage.setItem(CACHE_KEY, JSON.stringify(local));
      // 标记 8 天前
      const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
      localStorage.setItem(MIGRATION_MARKER, eightDaysAgo);
      mockGetSettings.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, maxContext: 8000 });

      await loadSettings();

      // 8 天前的标记 + 后端已有数据 → 清理 local
      expect(mockSetSettings).not.toHaveBeenCalled();
    });
  });
});
